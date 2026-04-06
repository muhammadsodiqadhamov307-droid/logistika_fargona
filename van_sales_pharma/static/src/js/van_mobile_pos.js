/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy, useExternalListener } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { session } from "@web/session";

// Number formatting helpers outside component scope for general use if needed
const formatNumberWithCommas = (number) => {
    if (number === null || number === undefined || number === '') return '';
    const numStr = String(number).replace(/,/g, '');
    const num = parseFloat(numStr);
    if (isNaN(num)) return '';
    return num.toLocaleString('en-US');
};

const parseFormattedNumber = (formattedNumber) => {
    if (!formattedNumber) return 0;
    const cleaned = String(formattedNumber).replace(/,/g, '');
    const num = parseFloat(cleaned);
    return isNaN(num) ? 0 : num;
};

export class VanMobilePos extends Component {
    setup() {
        this.action = useService("action");
        this.session = session;
        this.notification = useService("notification");

        useExternalListener(window, "click", this.onWindowClick);

        this.state = useState({
            screen: 'products', // clients, products, checkout, kirim
            error: null,

            // Data
            clients: [],
            inventory: [],
            allProducts: [],

            // Active selection
            selectedClient: { id: 0, name: 'Naqt savdo', total_due: 0 },
            cart: {}, // productId: {qty, product}

            // Post-checkout
            newNasiyaId: null,
            nasiyaAmount: 0,
            kirimAmount: 0,

            loading: true,
            searchQuery: '',
            productSearchQuery: '',

            // Quick Actions (Kirim / Chiqim)
            showQuickAction: false,
            quickActionType: 'kirim', // 'kirim' or 'chiqim'
            quickActionAmount: '',
            quickActionNote: '',
            quickActionPartnerId: '',
            quickActionExpenseType: 'daily',

            // Payment History
            paymentHistory: [],
            paymentHistoryType: 'kirim',
            editingPaymentId: null,

            // Action Menu (3-dots)
            showActionMenu: false,

            // Agent Picker (admin)
            showAgentPicker: false,
            agentsList: [],

            // Requests (So'rovlar)
            requestsList: [],
            requestFilter: 'draft',
            requestPartnerId: '',
            requestPartnerName: '',
            requestNote: '',
            requestCart: {},

            // Picker Modals for newRequest form
            showClientPickerModal: false,
            clientSearchModal: '',

            // New Client Modal
            showNewClientModal: false,
            newClientData: {
                name: '',
                phone: '',
                telegram_chat_id: '',
            },

            // Mahsulot Yuklash (Trip Load) features
            currentAgent: null,
            taminotchis: [],
            selectedTaminotchiId: null,
            tripsList: [],
            activeTrip: null,
            tripDate: new Date().toISOString().split('T')[0], // Defaults to today
            tripNote: '',
            tripCart: {},
            tripSelectionCounter: 0,
            showYuklashPreviewModal: false,
            yuklashPreviewLines: [],
            yuklashPreviewTotal: 0,

            pollingInterval: null,

            // Offline Support
            isOnline: navigator.onLine,
            syncQueue: [],
            isSyncing: false,

            // Client Report
            clientReport: null,
            clientReportLoading: false,
            clientReportDateFrom: '',
            clientReportDateTo: '',
            clientReportTelegramChatId: '',
            clientReportTelegramSaving: false,
            clientsScrollTop: 0,

            // So'rov -> POS integration
            sourceSorovId: null,   // set when fulfilling a request via POS flow,
            clientReportClientId: null,
            clientReportExpandedRows: {}, // order_index: true/false

            // Client Report Edit Mode
            editingTxnId: null,      // tx.id if currently editing
            editKirimAmount: '',     // bound to input
            editSotuvLines: {},      // {line_id: {qty, price, price_formatted}}

            // Custom Kirim Flow
            showKirimClientModal: false,
            showKirimAmountModal: false,
            kirimClientSearch: '',
            selectedKirimClientId: null,
            selectedKirimClientName: '',
            selectedKirimClientDebt: 0,
            kirimAmountInput: '',
            kirimNotes: '',
        });

        // Expose formatting function to template
        this.formatNumber = formatNumberWithCommas;

        // Initialize connection listeners
        useExternalListener(window, "online", this.onOnline.bind(this));
        useExternalListener(window, "offline", this.onOffline.bind(this));

        onWillStart(async () => {
            // CRITICAL: wait for IDB to be ready BEFORE loading data
            // Without this, this.db is null and all IDB reads return empty
            await this.initIDB();

            await this.loadCurrentAgent();

            await Promise.all([
                this.loadClients(),
                this.loadInventory(),
                this.loadAllProducts(),
                this.loadTaminotchis()
            ]);

            this.state.pollingInterval = setInterval(() => {
                if (this.state.isOnline) this.loadInventorySilent();
            }, 15000);

            // Hide Odoo Navbar for standalone app experience
            this.posStyle = document.createElement('style');
            this.posStyle.id = 'van-pos-fullscreen-style';
            this.posStyle.innerHTML = `
                .o_main_navbar { display: none !important; }
                .o_web_client { padding-top: 0 !important; }
                .o_content { overflow: auto !important; height: 100vh !important; }
            `;
            document.head.appendChild(this.posStyle);
            document.body.classList.add('van-pos-active');
        });

        onWillDestroy(() => {
            if (this.state.pollingInterval) {
                clearInterval(this.state.pollingInterval);
            }
            if (this.posStyle) {
                this.posStyle.remove();
            }
            document.body.classList.remove('van-pos-active');
        });
    }

    onOnline() {
        this.state.isOnline = true;
        document.body.style.overscrollBehavior = 'auto';
        this.showToast("Internet tiklandi. Ma'lumotlar sinxronlanmoqda...", "success");
        // Refresh data from server now that we're back online
        Promise.all([
            this.loadClients(),
            this.loadInventory(),
            this.loadCurrentAgent(),
            this.loadTaminotchis(),
        ]);
        this.syncOfflineTransactions();
    }

    onOffline() {
        this.state.isOnline = false;
        document.body.style.overscrollBehavior = 'none';
        this.showToast("Internetdan uzildi. Offline rejimda ishlayapsiz.", "warning");
    }

    // --- Toast Notification ---
    showToast(message, type = "info") {
        if (this.notification) {
            this.notification.add(message, { type: type });
        } else {
            console.log(`[Toast ${type}]: ${message}`);
        }
    }

    // --- IndexedDB Wrapper ---
    async initIDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('VanSalesAppDB', 1);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('clients')) {
                    db.createObjectStore('clients', { keyPath: 'id' });
                }
                if (!db.objectStoreNames.contains('inventory')) {
                    db.createObjectStore('inventory', { keyPath: 'product_id' });
                }
                if (!db.objectStoreNames.contains('allProducts')) {
                    db.createObjectStore('allProducts', { keyPath: 'id' });
                }
                if (!db.objectStoreNames.contains('agent')) {
                    db.createObjectStore('agent', { keyPath: 'id' }); // Dummy id 1
                }
                if (!db.objectStoreNames.contains('taminotchis')) {
                    db.createObjectStore('taminotchis', { keyPath: 'id' });
                }
                if (!db.objectStoreNames.contains('syncQueue')) {
                    db.createObjectStore('syncQueue', { keyPath: 'offline_id' });
                }
            };

            request.onsuccess = (event) => {
                this.db = event.target.result;
                this.loadQueueFromIDB();
                resolve();
            };

            request.onerror = (event) => {
                console.error("IndexedDB error:", event.target.error);
                reject(event.target.error);
            };
        });
    }

    async saveToIDB(storeName, data, isArray = true) {
        if (!this.db) return;
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readwrite');
            const store = transaction.objectStore(storeName);

            // Clear existing data before bulk save
            store.clear();

            // Deep clone to remove Owl Proxies to prevent DataCloneError
            const cleanData = JSON.parse(JSON.stringify(data));

            if (isArray) {
                cleanData.forEach(item => {
                    // Safety guard: Ensure the item has the required key for the store
                    const keyPath = store.keyPath;
                    if (item[keyPath] !== undefined && item[keyPath] !== null && item[keyPath] !== false) {
                        store.put(item);
                    } else {
                        console.warn(`Skipping save to IDB store ${storeName}: Missing or invalid key`, item);
                    }
                });
            } else {
                store.put(cleanData);
            }

            transaction.oncomplete = () => resolve();
            transaction.onerror = (e) => reject(e.target.error);
        });
    }

    async getFromIDB(storeName) {
        if (!this.db) return [];
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readonly');
            const store = transaction.objectStore(storeName);
            const request = store.getAll();

            request.onsuccess = () => resolve(request.result);
            request.onerror = (e) => reject(e.target.error);
        });
    }

    // Single item IDB ops for Queue
    async saveQueueItem(item) {
        if (!this.db) return;
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['syncQueue'], 'readwrite');
            const store = transaction.objectStore('syncQueue');
            // Remove Proxy
            const cleanItem = JSON.parse(JSON.stringify(item));
            store.put(cleanItem);
            transaction.oncomplete = () => resolve();
            transaction.onerror = (e) => reject(e.target.error);
        });
    }

    async deleteQueueItem(offlineId) {
        if (!this.db) return;
        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction(['syncQueue'], 'readwrite');
            const store = transaction.objectStore('syncQueue');
            store.delete(offlineId);
            transaction.oncomplete = () => resolve();
            transaction.onerror = (e) => reject(e.target.error);
        });
    }

    async loadQueueFromIDB() {
        try {
            const queue = await this.getFromIDB('syncQueue');
            this.state.syncQueue = queue || [];
        } catch (e) {
            console.error("Failed loading queue from IDB", e);
        }
    }

    // Add unique UUID generator
    generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    // --- End Offline Wrappers ---

    onWindowClick = (ev) => {
        if (!this.state.showActionMenu) return;

        const menu = document.getElementById('dots-menu');
        const dotsButton = document.getElementById('dots-button');

        if (menu && dotsButton) {
            if (!menu.contains(event.target) && !dotsButton.contains(event.target)) {
                this.state.showActionMenu = false;
            }
        }
    }

    async openAgentPicker() {
        if (!this.state.currentAgent || !this.state.currentAgent.is_admin) return;
        try {
            const agents = await rpc('/van/pos/get_agents', {});
            this.state.agentsList = agents || [];
            this.state.showAgentPicker = true;
        } catch (e) {
            this.showToast("Agentlar ro'yxatini yuklashda xatolik", "danger");
        }
    }

    async selectAgentFromModal(agentId) {
        try {
            await rpc('/van/pos/set_agent_session', { agent_id: agentId });
            this.state.showAgentPicker = false;
            // Refresh agent info and inventory with newly selected agent
            await this.loadCurrentAgent();
            await this.loadClients();
            await this.loadInventory();
            this.state.error = null;
            this.showToast("Agent o'zgartirildi", "success");
        } catch (e) {
            this.showToast("Agent almashtirishda xatolik", "danger");
        }
    }

    async loadClients() {
        this.state.loading = true;
        try {
            // Always load from IDB cache first so offline reloads work immediately
            const cached = await this.getFromIDB('clients');
            if (cached && cached.length > 0) {
                // Preserve server-side sort order (sort_order field)
                this.state.clients = cached.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
            }
            // Then refresh from server if online
            if (this.state.isOnline) {
                const result = await rpc("/van/pos/get_clients", {});
                this.state.clients = result;
                await this.saveToIDB('clients', result);
            } else if (!this.state.clients.length) {
                // Only warn if cache was also empty
                this.showToast("Offline rejimda mijozlar keshi bo'sh. Avval onlayn ulanib cache qiling.", "warning");
            }
        } catch (e) {
            console.error(e);
            const cached = await this.getFromIDB('clients');
            if (cached && cached.length > 0) this.state.clients = cached;
        }
        this.state.loading = false;
    }

    async loadInventory() {
        try {
            // Always load from IDB cache first so offline reloads work immediately
            const cached = await this.getFromIDB('inventory');
            if (cached && cached.length > 0) {
                this.state.inventory = cached;
            }
            // Then refresh from server if online
            if (this.state.isOnline) {
                const result = await rpc("/van/pos/get_inventory?t=" + Date.now(), {});
                this.state.inventory = result;
                await this.saveToIDB('inventory', result);
            }
        } catch (e) {
            console.error(e);
            const cached = await this.getFromIDB('inventory');
            if (cached && cached.length > 0) this.state.inventory = cached;
        }
    }

    async loadCurrentAgent() {
        // Always load from IDB cache first
        try {
            const cached = await this.getFromIDB('agent');
            if (cached && cached.length > 0) {
                this.state.currentAgent = cached[0];
            }
        } catch (e) {
            console.error("Failed to load agent from IDB:", e);
        }

        if (!this.state.isOnline) {
            // If offline and no cached agent, we can't proceed
            if (!this.state.currentAgent) {
                this.showToast("Offline rejimda agent ma'lumotlari mavjud emas.", "warning");
            }
            return;
        }

        try {
            const result = await rpc('/van/pos/get_current_agent');
            if (result) {
                this.state.currentAgent = result;
                this.state.error = null;
                await this.saveToIDB('agent', [result], false); // Save as array for consistency with getFromIDB
            }
        } catch (e) {
            console.error("Agent yuklashda xatolik:", e);
            // If online fetch fails, rely on cached data if available
            if (!this.state.currentAgent) {
                this.showToast("Agent ma'lumotlarini yuklashda xatolik. Offline rejimga o'tildi.", "danger");
            }
        }
    }



    async loadTaminotchis() {
        try {
            // Always load from IDB cache first
            const cached = await this.getFromIDB('taminotchis');
            if (cached && cached.length > 0) {
                this.state.taminotchis = cached;
            }
            // Then refresh from server if online
            if (this.state.isOnline) {
                const result = await rpc("/van/pos/get_taminotchis", {});
                this.state.taminotchis = result;
                await this.saveToIDB('taminotchis', result);
            }
            if (this.state.taminotchis && this.state.taminotchis.length > 0) {
                if (this.state.currentAgent && this.state.currentAgent.default_taminotchi_id) {
                    this.state.selectedTaminotchiId = this.state.currentAgent.default_taminotchi_id;
                } else {
                    this.state.selectedTaminotchiId = this.state.taminotchis[0].id;
                }
            }
        } catch (e) {
            console.error("Taminotchi rpc error:", e);
            const cached = await this.getFromIDB('taminotchis');
            if (cached && cached.length > 0) {
                this.state.taminotchis = cached;
                if (this.state.currentAgent && this.state.currentAgent.default_taminotchi_id) {
                    this.state.selectedTaminotchiId = this.state.currentAgent.default_taminotchi_id;
                } else {
                    this.state.selectedTaminotchiId = cached[0].id;
                }
            }
        }
    }

    async loadAllProducts() {
        try {
            const result = await rpc("/van/pos/get_all_products?t=" + Date.now(), {});
            this.state.allProducts = result;
        } catch (e) {
            console.error("Xatolik: Barcha mahsulotlarni yuklash imkonsiz.", e);
        }
    }

    async openTripsList() {
        this.state.loading = true;
        try {
            const result = await rpc("/van/pos/get_trips", {});
            if (result.success) {
                this.state.tripsList = result.trips || [];
                this.state.screen = 'trips_list';

                // reset trip creation form
                this.state.tripDate = new Date().toISOString().split('T')[0];
                this.state.tripNote = '';
                this.state.tripCart = {};
                this.state.activeTrip = null;
            } else {
                this.state.error = result.error || "Sayohatlarni o'qishda xatolik";
            }
        } catch (e) {
            this.state.error = "Tarmoqda xatolik: Sayohatlarni o'qish xatosi";
        }
        this.state.loading = false;
    }

    async loadInventorySilent() {
        try {
            const freshInventory = await rpc("/van/pos/get_inventory?t=" + Date.now(), {});
            this.state.inventory = freshInventory;

            // Reconcile and clean up cart if stock dropped unexpectedly
            for (const [productIdStr, item] of Object.entries(this.state.cart)) {
                const pId = parseInt(productIdStr);
                const freshProduct = freshInventory.find(p => p.product_id === pId);

                if (!freshProduct || freshProduct.remaining <= 0) {
                    delete this.state.cart[pId]; // Item vanished or solid out
                } else if (item.qty > freshProduct.remaining) {
                    this.state.cart[pId].qty = freshProduct.remaining; // Cap maximum to new limit
                    this.state.cart[pId].product.remaining = freshProduct.remaining;
                } else {
                    this.state.cart[pId].product.remaining = freshProduct.remaining; // Update strictly for UI
                }
            }
        } catch (e) {
            console.error("Silent stock polling failed:", e);
        }
    }

    selectClient(client) {
        this.state.selectedClient = client;
        this.state.screen = 'products';
    }

    // --- New Client Methods ---
    openNewClientForm() {
        this.state.newClientData = { name: '', phone: '', telegram_chat_id: '' };
        this.state.error = null;
        this.state.showNewClientModal = true;
    }

    closeNewClientForm() {
        this.state.showNewClientModal = false;
    }

    formatPhoneNumber(ev) {
        let value = ev.target.value.replace(/\D/g, ''); // Remove non-digits
        if (value.length > 0) {
            if (!value.startsWith('998') && value.length <= 9) {
                value = '998' + value; // Auto-prefix with 998 if reasonable
            }
        }

        let formatted = '+';
        if (value.length > 0) formatted += value.substring(0, 3);
        if (value.length > 3) formatted += ' ' + value.substring(3, 5);
        if (value.length > 5) formatted += ' ' + value.substring(5, 8);
        if (value.length > 8) formatted += ' ' + value.substring(8, 10);
        if (value.length > 10) formatted += ' ' + value.substring(10, 12);

        ev.target.value = formatted;
        this.state.newClientData.phone = formatted;
    }

    async submitNewClient() {
        try {
            this.state.loading = true;
            this.state.error = null;

            const data = this.state.newClientData;
            if (!data.name.trim() || !data.phone.trim()) {
                this.state.error = 'Iltimos, ism va telefon raqamini kiriting.';
                this.state.loading = false;
                return;
            }

            const response = await rpc('/van/pos/create_client', data);

            if (response && response.success) {
                this.showToast(response.message || "Mijoz yaratildi", "success");
                this.closeNewClientForm();

                // Refresh clients remotely and locally
                await this.loadClients();

                // Select the newly created client
                const newClient = this.state.clients.find(c => c.id === response.client_id);
                if (newClient) {
                    this.selectClient(newClient);
                }
            } else {
                this.state.error = response?.error || 'Xatolik yuz berdi';
            }
        } catch (e) {
            console.error("Error creating client", e);
            this.state.error = 'Tarmoq xatosi yoki server ishlamayapti.';
        } finally {
            this.state.loading = false;
        }
    }


    get filteredClients() {
        if (!this.state.searchQuery) return this.state.clients;
        return this.state.clients.filter(c => c.name.toLowerCase().includes(this.state.searchQuery.toLowerCase()));
    }



    get filteredInventory() {
        let base = this.state.inventory.filter(p => p.remaining > 0);
        if (!this.state.productSearchQuery) return base;
        return base.filter(p => p.name.toLowerCase().includes(this.state.productSearchQuery.toLowerCase()));
    }

    get filteredAllProducts() {
        let base = this.state.allProducts;
        if (!this.state.productSearchQuery) return base;
        return base.filter(p => p.name.toLowerCase().includes(this.state.productSearchQuery.toLowerCase()));
    }

    get filteredRequests() {
        if (this.state.requestFilter === 'all') {
            return this.state.requestsList;
        }
        return this.state.requestsList.filter(req => req.state === this.state.requestFilter);
    }

    get filteredModalClients() {
        if (!this.state.clientSearchModal) {
            return this.state.clients;
        }
        const search = this.state.clientSearchModal.toLowerCase();
        return this.state.clients.filter(client =>
            client.name.toLowerCase().includes(search)
        );
    }

    get requestCartTotal() {
        return Object.values(this.state.requestCart).reduce((sum, item) => sum + ((parseFloat(item.qty) || 0) * item.price), 0);
    }

    changeRequestLineQty(product, delta) {
        if (!this.state.requestCart) this.state.requestCart = {};
        const pId = product.product_id;
        if (!this.state.requestCart[pId]) {
            if (delta > 0) {
                this.state.requestCart[pId] = { product_id: pId, qty: delta, price: product.price };
            }
        } else {
            this.state.requestCart[pId].qty += delta;
            if (this.state.requestCart[pId].qty <= 0) {
                delete this.state.requestCart[pId];
            }
        }
    }

    setRequestLineQty(product, ev) {
        if (!this.state.requestCart) this.state.requestCart = {};
        const pId = product.product_id;

        let val = ev.target.value;
        if (val === '') {
            // Allow empty string while typing, but initialize object if missing
            if (!this.state.requestCart[pId]) {
                this.state.requestCart[pId] = { product_id: pId, qty: '', price: product.price };
            } else {
                this.state.requestCart[pId].qty = '';
            }
            return;
        }

        let newQty = parseInt(val);
        if (isNaN(newQty) || newQty <= 0) {
            delete this.state.requestCart[pId];
            ev.target.value = 0;
        } else {
            if (!this.state.requestCart[pId]) {
                this.state.requestCart[pId] = { product_id: pId, qty: newQty, price: product.price };
            } else {
                this.state.requestCart[pId].qty = newQty;
            }
            // Optional: ev.target.value = newQty; // Not necessary if bound cleanly
        }
    }

    get tripCartTotal() {
        return Object.values(this.state.tripCart).reduce((sum, item) => sum + ((parseFloat(item.qty) || 0) * item.price), 0);
    }

    nextTripSelectionOrder() {
        this.state.tripSelectionCounter += 1;
        return this.state.tripSelectionCounter;
    }

    changeTripLineQty(product, delta) {
        if (!this.state.tripCart) this.state.tripCart = {};
        const pId = product.product_id;
        if (!this.state.tripCart[pId]) {
            if (delta > 0) {
                this.state.tripCart[pId] = {
                    product_id: pId,
                    qty: delta,
                    price: product.cost_price,
                    selection_order: this.nextTripSelectionOrder(),
                };
            }
        } else {
            this.state.tripCart[pId].qty += delta;
            if (this.state.tripCart[pId].qty <= 0) {
                delete this.state.tripCart[pId];
            }
        }
    }

    setTripLineQty(product, ev) {
        if (!this.state.tripCart) this.state.tripCart = {};
        const pId = product.product_id;

        let val = ev.target.value;
        if (val === '') {
            if (!this.state.tripCart[pId]) {
                this.state.tripCart[pId] = {
                    product_id: pId,
                    qty: '',
                    price: product.cost_price,
                    selection_order: this.nextTripSelectionOrder(),
                };
            } else {
                this.state.tripCart[pId].qty = '';
            }
            return;
        }

        let newQty = parseInt(val);
        if (isNaN(newQty) || newQty <= 0) {
            delete this.state.tripCart[pId];
            ev.target.value = 0;
        } else {
            if (!this.state.tripCart[pId]) {
                this.state.tripCart[pId] = {
                    product_id: pId,
                    qty: newQty,
                    price: product.cost_price,
                    selection_order: this.nextTripSelectionOrder(),
                };
            } else {
                this.state.tripCart[pId].qty = newQty;
            }
        }
    }

    get cartItems() {
        return Object.values(this.state.cart);
    }

    get cartTotal() {
        return this.cartItems.reduce((sum, item) => sum + ((parseFloat(item.qty) || 0) * item.custom_price), 0);
    }

    addToCart(product) {
        if (this.state.cart[product.product_id]) {
            if (this.state.cart[product.product_id].qty < product.remaining) {
                this.state.cart[product.product_id].qty++;
            }
        } else {
            if (product.remaining > 0) {
                this.state.cart[product.product_id] = { qty: 1, product: product, custom_price: product.price };
            }
        }
    }

    // --- LOCAL CACHE UPDATERS ---
    updateLocalClientBalance(partnerId, deltaAmount) {
        if (!partnerId || deltaAmount === 0) return;
        const client = this.state.clients.find(c => c.id === partnerId);
        if (client) {
            client.total_due = (client.total_due || 0) + deltaAmount;
            // Background save to cache so it reflects immediately
            this.saveToIDB('clients', this.state.clients);
        }
    }

    removeFromCart(productId) {
        if (this.state.cart[productId]) {
            this.state.cart[productId].qty--;
            if (this.state.cart[productId].qty <= 0) {
                delete this.state.cart[productId];
            }
        }
    }

    setCartQuantity(product, ev) {
        let val = ev.target.value;
        if (val === '') {
            if (this.state.cart[product.product_id]) {
                this.state.cart[product.product_id].qty = '';
            } else {
                this.state.cart[product.product_id] = { qty: '', product: product, custom_price: product.price };
            }
            return;
        }

        let newQty = parseFloat(val);
        if (isNaN(newQty) || newQty <= 0) {
            delete this.state.cart[product.product_id];
            return;
        }

        if (newQty > product.remaining) {
            newQty = product.remaining;
        }

        if (this.state.cart[product.product_id]) {
            this.state.cart[product.product_id].qty = newQty;
        } else {
            this.state.cart[product.product_id] = { qty: newQty, product: product, custom_price: product.price };
        }
    }

    // --- Input Handlers for formatting ---
    setNasiyaKirimAmountForm(ev) {
        // Remove trailing commas mapping errors
        const cursorPosition = ev.target.selectionStart;
        const oldLength = ev.target.value.length;

        const numericValue = parseFormattedNumber(ev.target.value);
        if (isNaN(numericValue) || ev.target.value === '') {
            this.state.kirimAmount = '';
        } else {
            this.state.kirimAmount = formatNumberWithCommas(numericValue);
        }

        // Try to maintain cursor position
        setTimeout(() => {
            if (ev.target) {
                const newLength = ev.target.value.length;
                let newPos = cursorPosition + (newLength - oldLength);
                ev.target.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }

    setQuickActionAmountForm(ev) {
        const cursorPosition = ev.target.selectionStart;
        const oldLength = ev.target.value.length;

        const numericValue = parseFormattedNumber(ev.target.value);
        if (isNaN(numericValue) || ev.target.value === '') {
            this.state.quickActionAmount = '';
        } else {
            this.state.quickActionAmount = formatNumberWithCommas(numericValue);
        }

        setTimeout(() => {
            if (ev.target) {
                const newLength = ev.target.value.length;
                let newPos = cursorPosition + (newLength - oldLength);
                ev.target.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }

    setEditKirimAmountForm(ev) {
        const cursorPosition = ev.target.selectionStart;
        const oldLength = ev.target.value.length;

        const numericValue = parseFormattedNumber(ev.target.value);
        if (isNaN(numericValue) || ev.target.value === '') {
            this.state.editKirimAmount = '';
        } else {
            this.state.editKirimAmount = formatNumberWithCommas(numericValue);
        }

        setTimeout(() => {
            if (ev.target) {
                const newLength = ev.target.value.length;
                let newPos = cursorPosition + (newLength - oldLength);
                ev.target.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }

    setEditSotuvPriceForm(lineId, ev) {
        const cursorPosition = ev.target.selectionStart;
        const oldLength = ev.target.value.length;

        const numericValue = parseFormattedNumber(ev.target.value);
        if (isNaN(numericValue) || ev.target.value === '') {
            this.state.editSotuvLines[lineId].price_formatted = '';
            this.state.editSotuvLines[lineId].price = 0;
        } else {
            this.state.editSotuvLines[lineId].price_formatted = formatNumberWithCommas(numericValue);
            this.state.editSotuvLines[lineId].price = numericValue;
        }

        setTimeout(() => {
            if (ev.target) {
                const newLength = ev.target.value.length;
                let newPos = cursorPosition + (newLength - oldLength);
                ev.target.setSelectionRange(newPos, newPos);
            }
        }, 0);
    }

    setCartPrice(product, ev) {
        let newPrice = parseFormattedNumber(ev.target.value);
        if (isNaN(newPrice) || newPrice < 0) {
            newPrice = product.price; // fallback to default
        }
        if (this.state.cart[product.product_id]) {
            this.state.cart[product.product_id].custom_price = newPrice;
        }
    }

    goToCheckout() {
        if (this.cartItems.length > 0) {
            this.state.screen = 'checkout';
        }
    }

    async submitOrder() {
        this.state.loading = true;
        const validCartItems = this.cartItems.filter(item => item.qty && parseFloat(item.qty) > 0);
        if (validCartItems.length === 0) {
            this.showToast("Hech qanday mahsulot kiritilmadi.", "warning");
            this.state.loading = false;
            return;
        }

        const lines = validCartItems.map(item => ({
            product_id: item.product.product_id,
            qty: parseFloat(item.qty),
            price: item.custom_price
        }));

        const isNasiya = !!(this.state.selectedClient.id && this.state.selectedClient.id !== 0);
        const data = {
            partner_id: this.state.selectedClient.id || false,
            lines: lines,
            isNasiya: isNasiya
        };

        if (this.state.isOnline) {
            try {
                const result = await rpc("/van/pos/submit_order", data);

                if (result.success) {
                    this.loadInventorySilent();

                    // If this sale was created from a So'rov, mark it as fulfilled
                    if (this.state.sourceSorovId) {
                        const sorovId = this.state.sourceSorovId;
                        this.state.sourceSorovId = null;
                        try {
                            await rpc("/van/pos/fulfill_request", { request_id: sorovId });
                        } catch (e) {
                            console.error("So'rovni bajarildi deb belgilashda xatolik:", e);
                        }
                    }

                    if (!isNasiya) {
                        // Naqt savdo: money is already received, skip payment screen.
                        this.resetToStart();
                        this.showToast("Savdo muvaffaqiyatli saqlandi!", "success");
                    } else {
                        // Nasiya: prompt for partial/full payment.
                        this.state.newNasiyaId = result.nasiya_id;
                        this.state.nasiyaAmount = result.nasiya_amount;
                        this.state.kirimAmount = formatNumberWithCommas(result.nasiya_amount);
                        this.state.screen = 'kirim';
                        this.showToast("Nasiya saqlandi. To'lovni kiriting.", "success");
                    }
                } else {
                    this.state.error = result.error || "Savdo amalga oshmadi.";
                }
            } catch (e) {
                this.state.error = "Tarmoqda xatolik: Savdo amalga oshmadi.";
            }
        } else {
            // OFFLINE SAVE
            const offline_id = this.generateUUID();
            const tx = {
                offline_id: offline_id,
                type: 'sale',
                timestamp: new Date().toISOString(),
                data: data
            };
            await this.saveQueueItem(tx);
            this.state.syncQueue.push(tx);

            // Local deduct logic (UX)
            for (let item of this.cartItems) {
                let invLine = this.state.inventory.find(i => i.product_id === item.product.product_id);
                if (invLine) invLine.remaining -= item.qty;
            }
            await this.saveToIDB('inventory', this.state.inventory);

            if (!isNasiya) {
                this.resetToStart();
                this.showToast("Offline saqlandi. Internet bo'lganda sinxronlanadi.", "warning");
            } else {
                // For Nasiya, offline we can't get a real nasiya_id. 
                // Add the whole cart amount to local client balance
                const orderAmount = this.cartItems.reduce((acc, item) => acc + (item.qty * item.custom_price), 0);
                this.updateLocalClientBalance(this.state.selectedClient.id, orderAmount);

                this.resetToStart();
                this.showToast("Offline Nasiya saqlandi (Kirim uchun alohida amaliyot ishlating).", "warning");
            }
        }
        this.state.loading = false;
    }

    async submitKirim(paymentMethod = 'cash') {
        const amount = parseFormattedNumber(this.state.kirimAmount);
        if (amount >= 0) {
            this.state.loading = true;
            if (this.state.isOnline && this.state.newNasiyaId) {
                try {
                    await rpc("/van/pos/submit_kirim", {
                        nasiya_id: this.state.newNasiyaId,
                        amount: amount,
                        payment_method: paymentMethod
                    });

                    // Locally update balance: (Total Nasiya - Paid Kirim)
                    const delta = this.state.nasiyaAmount - amount;
                    this.updateLocalClientBalance(this.state.selectedClient.id, delta);

                    this.showToast("To'lov saqlandi", "success");
                } catch (e) {
                    console.error("Kirim failed", e);
                }
            } else if (!this.state.isOnline) {
                this.showToast("Nasiyaga offline qisman to'lov hozircha amalga oshirib bo'lmaydi. Uni mijoz oynasidan Kirim qiling", "error");
            }
        }
        this.resetToStart();
    }

    resetToStart() {
        this.state.screen = 'products';
        this.state.selectedClient = { id: 0, name: 'Naqt savdo', total_due: 0 };
        this.state.cart = {};
        this.state.newNasiyaId = null;
        this.state.searchQuery = '';
        this.state.productSearchQuery = '';
        this.state.showQuickAction = false;
        this.state.showActionMenu = false;
        this.state.requestsList = [];
        this.loadClients();
    }

    // --- QUICK ACTIONS ---
    openQuickAction(type) {
        this.state.quickActionType = type;
        this.state.quickActionAmount = '';
        this.state.quickActionNote = '';
        this.state.quickActionPartnerId = '';
        this.state.quickActionExpenseType = 'daily';
        this.state.showQuickAction = true;
    }

    closeQuickAction() {
        this.state.showQuickAction = false;
    }

    async submitQuickAction() {
        const amount = parseFormattedNumber(this.state.quickActionAmount);
        if (isNaN(amount) || amount <= 0) {
            this.state.error = "Iltimos summani to'g'ri kiriting.";
            return;
        }

        const data = {
            type: this.state.quickActionType,
            amount: amount,
            note: this.state.quickActionNote,
            partner_id: this.state.screen === 'products' ? this.state.selectedClient.id : (this.state.quickActionPartnerId ? parseInt(this.state.quickActionPartnerId) : null),
            expense_type: this.state.quickActionExpenseType
        };

        this.state.loading = true;

        if (this.state.isOnline) {
            try {
                if (this.state.editingPaymentId) {
                    // Update existing payment
                    const updateData = {
                        payment_id: this.state.editingPaymentId,
                        payment_type: this.state.quickActionType === 'kirim' ? 'in' : 'out',
                        amount: amount,
                        note: this.state.quickActionNote,
                        partner_id: data.partner_id,
                        expense_type: this.state.quickActionExpenseType
                    };
                    const result = await rpc("/van/pos/save_payment", updateData);
                    if (result.success) {
                        this.showToast("Amaliyot yangilandi!", "success");
                        this.closeQuickAction();
                        await this.openPaymentHistory(this.state.paymentHistoryType);
                    } else {
                        this.state.error = result.error || "Yangilashda xatolik";
                    }
                } else {
                    // Create new payment (retains original logic)
                    const result = await rpc("/van/pos/submit_quick_action", data);

                    if (result.success) {
                        // Locally update balance if this was a kirim from a client
                        if (this.state.quickActionType === 'kirim' && data.partner_id) {
                            this.updateLocalClientBalance(data.partner_id, -amount);
                        }

                        this.loadCurrentAgent(); // Refresh agent balance if it was a salary withdrawal
                        this.closeQuickAction();
                        this.showToast("Amaliyot saqlandi!", "success");

                        // If we are currently inside the history view, refresh it
                        if (this.state.screen === 'payment_history') {
                            await this.openPaymentHistory(this.state.paymentHistoryType);
                        }
                    } else {
                        this.state.error = result.error || "Amaliyot saqlanmadi.";
                    }
                }
            } catch (e) {
                this.state.error = "Tarmoqda xatolik: Amaliyot bajarilmadi.";
            }
        } else {
            // OFFLINE SAVE (Only for creations, edits not allowed offline)
            const offline_id = this.generateUUID();
            const tx = {
                offline_id: offline_id,
                type: 'chiqim', // Assuming quickAction is generally Chiqim unless type is 'kirim' handled above
                timestamp: new Date().toISOString(),
                data: data
            };

            if (this.state.quickActionType === 'kirim') {
                tx.type = 'kirim';
                if (data.partner_id) {
                    this.updateLocalClientBalance(data.partner_id, -amount);
                }
            }

            await this.saveQueueItem(tx);
            this.state.syncQueue.push(tx);

            this.closeQuickAction();
            this.showToast("Offline saqlandi. Internet bo'lganda sinxronlanadi.", "warning");
        }

        this.state.loading = false;
    }

    // --- OFFLINE SYNC LOGIC ---
    async syncOfflineTransactions() {
        if (!this.state.isOnline || this.state.syncQueue.length === 0 || this.state.isSyncing) return;

        this.state.isSyncing = true;
        this.showToast(`Sinxronlanmoqda... (${this.state.syncQueue.length} ta amaliyot)`, "info");

        try {
            // Only send the ones currently in queue
            const transactionsToSend = [...this.state.syncQueue];

            const result = await rpc("/van/pos/sync_offline", {
                transactions: transactionsToSend
            });

            if (result.status === 'success' || result.status === 'partial_success') {
                // Remove synced items
                for (let syncedId of result.synced) {
                    await this.deleteQueueItem(syncedId);
                    this.state.syncQueue = this.state.syncQueue.filter(t => t.offline_id !== syncedId);
                }

                if (result.errors && result.errors.length > 0) {
                    this.showToast("Ba'zi amaliyotlar sinxronlanmadi. Buxgalteriyaga murojaat qiling.", "error");
                    console.error("Sync Errors:", result.errors);
                } else {
                    this.showToast("Barcha ma'lumotlar sinxronlandi ✅", "success");
                }

                // Refresh data if possible
                this.loadInventorySilent();
                this.loadClients();
                this.loadCurrentAgent();
            }
        } catch (e) {
            console.error("Sinxronlashda xato:", e);
            this.showToast("Sinxronlashda tarmoq xatosi.", "error");
        }

        this.state.isSyncing = false;
    }

    goToOfflineQueue() {
        this.state.screen = 'offline_queue';
        this.state.showActionMenu = false;
    }

    // --- REQUESTS (SO'ROVLAR) ---
    async openRequestsList() {
        this.state.loading = true;
        try {
            const result = await rpc("/van/pos/get_requests", {});
            if (result.success) {
                this.state.requestsList = result.requests || [];
                this.state.screen = 'requests_list';
                this.state.requestFilter = 'draft';
                this.state.requestPartnerId = '';
                this.state.requestNote = '';
                this.state.requestCart = {};
                this.state.activeRequest = null;
            } else {
                this.state.error = result.error || "So'rovlarni o'qishda xatolik";
            }
        } catch (e) {
            this.state.error = "Tarmoqda xatolik";
        }
        this.state.loading = false;
    }

    // Modal Picker Handlers
    openClientPicker() {
        this.state.clientSearchModal = '';
        this.state.showClientPickerModal = true;
    }

    closeClientPicker() {
        this.state.showClientPickerModal = false;
    }

    // ===========================================
    // Custom Kirim Creation Flow (Redesign)
    // ===========================================
    get filteredKirimClients() {
        const clientPool = this.state.clients.filter(c => c.id !== 0);
        if (!this.state.kirimClientSearch) return clientPool;
        const q = this.state.kirimClientSearch.toLowerCase();
        return clientPool.filter(c =>
            (c.name && c.name.toLowerCase().includes(q)) ||
            (c.phone && c.phone.includes(q))
        );
    }

    onNewPaymentClick() {
        this.state.showQuickAction = false;
        this.state.showKirimClientModal = false;
        this.state.showKirimAmountModal = false;
        this.state.editingPaymentId = null;
        if (this.state.paymentHistoryType === 'kirim') {
            this.openKirimClientModal();
        } else {
            this.openQuickAction(this.state.paymentHistoryType);
        }
    }

    openKirimClientModal() {
        this.state.showQuickAction = false;
        this.state.showKirimAmountModal = false;
        this.state.showKirimClientModal = true;
        this.state.kirimClientSearch = '';
        this.state.selectedKirimClientId = null;
        this.state.selectedKirimClientName = '';
        this.state.selectedKirimClientDebt = 0;
    }

    closeKirimClientModal() {
        this.state.showKirimClientModal = false;
    }

    selectTurliTushum() {
        this.selectKirimClient(null, 'Turli Tushum', 0);
    }

    selectKirimClient(clientId, clientName, clientDebt) {
        this.state.selectedKirimClientId = clientId;
        this.state.selectedKirimClientName = clientName;
        this.state.selectedKirimClientDebt = clientDebt;

        this.state.kirimAmountInput = '';
        this.state.kirimNotes = '';

        this.closeKirimClientModal();
        // Let the first modal unmount before opening the next one to avoid overlay stacking.
        setTimeout(() => {
            this.state.showKirimAmountModal = true;
        }, 0);
    }

    closeKirimAmountModal() {
        this.state.showKirimAmountModal = false;
    }

    setKirimFlowAmountForm(ev) {
        let val = ev.target.value.replace(/[^0-9]/g, '');
        if (!val) {
            this.state.kirimAmountInput = '';
            return;
        }
        let numericValue = parseInt(val, 10);
        this.state.kirimAmountInput = formatNumberWithCommas(numericValue);
    }

    async submitKirimFlow() {
        const rawAmount = parseInt(this.state.kirimAmountInput.replace(/,/g, ''), 10) || 0;
        if (rawAmount <= 0) {
            this.showToast("Summani kiriting", "danger");
            return;
        }

        this.state.loading = true;
        try {
            const params = {
                payment_type: 'in',
                amount: rawAmount,
                note: this.state.kirimNotes,
                partner_id: this.state.selectedKirimClientId ? this.state.selectedKirimClientId : false,
                expense_type: 'daily'
            };
            const result = await rpc("/van/pos/save_payment", params);
            if (result.success) {
                this.showToast("Kirim muvaffaqiyatli saqlandi", "success");
                this.closeKirimAmountModal();
                this.openPaymentHistory('kirim');
                this.loadClients(); // async reload background balances
            } else {
                this.showToast(result.error || "Xatolik yuz berdi", "danger");
            }
        } catch (e) {
            this.showToast("Tarmoq xatosi", "danger");
        }
        this.state.loading = false;
    }

    selectRequestClient(client) {
        this.state.requestPartnerId = client.id;
        this.state.requestPartnerName = client.name;
        this.closeClientPicker();
    }

    async updateRequestState(requestId, newState) {
        this.state.loading = true;
        try {
            const result = await rpc("/van/pos/update_request_state", {
                request_id: requestId,
                state: newState
            });
            if (result.success) {
                await this.openRequestsList();
            } else {
                this.state.error = result.error || "Holatni o'zgartirish muvaffaqiyatsiz bo'ldi";
            }
        } catch (e) {
            this.state.error = "Tarmoqda xatolik";
        }
        this.state.loading = false;
    }

    async submitRequest() {
        if (!this.state.requestPartnerId) {
            this.state.error = "Iltimos mijozni tanlang.";
            return;
        }

        const validLines = Object.values(this.state.requestCart).filter(l => l.qty > 0);

        if (validLines.length === 0 && !this.state.requestNote) {
            this.state.error = "Iltimos mahsulot tanlang yoki izoh kiriting.";
            return;
        }

        this.state.loading = true;
        try {
            const result = await rpc("/van/pos/submit_request", {
                partner_id: parseInt(this.state.requestPartnerId),
                lines: validLines,
                notes: this.state.requestNote
            });

            if (result.success) {
                // Refresh list and go backward
                await this.openRequestsList();
            } else {
                this.state.error = result.error || "So'rov saqlanmadi.";
            }
        } catch (e) {
            this.state.error = "Tarmoqda xatolik: So'rov saqlanmadi.";
        }
        this.state.loading = false;
    }

    viewRequestDetails(req) {
        // Create a deep copy of lines so edits don't affect main list until saved
        this.state.activeRequest = { ...req, lines: req.lines.map(l => ({ ...l })) };
        this.state.screen = 'request_details';
    }

    updateRequestLineQty(index, qtyStr) {
        const qty = parseFloat(qtyStr) || 0;
        const line = this.state.activeRequest.lines[index];
        line.qty = qty;
        line.subtotal = qty * line.price;
        this._recalcActiveRequestTotal();
    }

    updateRequestLinePrice(index, priceStr) {
        const price = parseFloat(priceStr) || 0;
        const line = this.state.activeRequest.lines[index];
        line.price = price;
        line.subtotal = line.qty * price;
        this._recalcActiveRequestTotal();
    }

    removeRequestLine(index) {
        this.state.activeRequest.lines.splice(index, 1);
        this._recalcActiveRequestTotal();
    }

    addRequestLine() {
        // Change screen to a product selector specially for request modification
        this.state.editingRequestId = this.state.activeRequest.id;
        this.state.screen = 'request_add_product';
    }

    addNewLineToActiveRequest(product) {
        // Check if exists
        const existing = this.state.activeRequest.lines.find(l => l.product_id === product.product_id);
        if (existing) {
            existing.qty += 1;
            existing.subtotal = existing.qty * existing.price;
        } else {
            this.state.activeRequest.lines.push({
                product_id: product.product_id,
                product_name: product.name,
                qty: 1,
                price: product.price, // using list_price from all_products effectively
                subtotal: product.price,
                image_url: product.image_url
            });
        }
        this._recalcActiveRequestTotal();
        this.showToast("Mahsulot qo'shildi!", "success");
        this.state.screen = 'request_details';
        this.state.productSearchQuery = '';
    }

    _recalcActiveRequestTotal() {
        let total = 0;
        for (let l of this.state.activeRequest.lines) {
            total += l.subtotal;
        }
        this.state.activeRequest.total_amount = total;
    }

    async saveRequestEdits(navigateBack = true) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const lines = this.state.activeRequest.lines.map(l => ({
                product_id: l.product_id,
                qty: l.qty,
                price: l.price
            }));
            // Guard: ensure all lines have a product_id
            const missingProduct = lines.find(l => !l.product_id);
            if (missingProduct) {
                this.state.error = "Barcha qatorlarda mahsulot bo'lishi kerak!";
                this.state.loading = false;
                return;
            }
            const res = await rpc("/van/pos/update_request", {
                request_id: this.state.activeRequest.id,
                lines
            });
            if (res.success) {
                this.showToast("So'rov saqlandi!");
                if (navigateBack) {
                    await this.openRequestsList();
                }
            } else {
                this.state.error = res.error || "Xatolik ro'y berdi.";
            }
        } catch (e) {
            this.state.error = "Tarmoqda xatolik: " + e.message;
        }
        this.state.loading = false;
    }

    async fulfillRequest() {
        if (!confirm("Ushbu so'rovni xarid qilib POS savdosiga o'tkazasizmi?")) return;

        const req = this.state.activeRequest;

        // 1. Save any pending edits first WITHOUT navigating away
        await this.saveRequestEdits(false);
        if (this.state.error) return;

        // 2. Find the client from the clients list (to get total_due etc.)
        const client = this.state.clients.find(c => c.id === req.partner_id) || {
            id: req.partner_id || 0,
            name: req.partner_name || 'Naqt savdo',
            total_due: 0
        };

        // 3. Pre-fill cart from So'rov lines
        //    state.cart format: { [product_id]: { qty, custom_price, product: {product_id, name, ...} } }
        const newCart = {};
        for (const line of req.lines) {
            if (!line.product_id) continue;
            // Try to find the product in inventory first, then allProducts
            const invProduct = this.state.inventory.find(p => p.product_id === line.product_id);
            const anyProduct = invProduct || this.state.allProducts.find(p => p.product_id === line.product_id);
            const productObj = anyProduct ? { ...anyProduct } : {
                product_id: line.product_id,
                name: line.product_name,
                price: line.price,
                remaining: 9999,
                image_url: line.image_url || ''
            };
            newCart[line.product_id] = {
                product: productObj,
                qty: line.qty,
                custom_price: line.price
            };
        }

        if (Object.keys(newCart).length === 0) {
            this.state.error = "So'rovda mahsulot yo'q!";
            return;
        }

        // 4. Apply to state
        this.state.cart = newCart;
        this.state.selectedClient = client;
        this.state.sourceSorovId = req.id;
        this.state.activeRequest = null;

        // 5. Navigate to existing checkout screen
        this.state.screen = 'checkout';
    }

    viewTripDetails(trip) {
        this.state.activeTrip = trip;
        this.state.screen = 'trip_details';
    }

    async submitTrip() {
        if (!this.state.currentAgent) {
            this.state.error = "Sizning akkauntingizga agent biriktirilmagan.";
            return;
        }

        const validLines = Object.values(this.state.tripCart)
            .filter(l => l.qty > 0)
            .sort((a, b) => (a.selection_order || 0) - (b.selection_order || 0));

        if (validLines.length === 0) {
            this.state.error = "Iltimos kamida bitta mahsulot tanlang.";
            return;
        }

        this.state.loading = true;
        try {
            const line_vals = validLines.map(l => {
                return {
                    product_id: l.product_id,
                    qty: l.qty,
                    price_unit: l.price
                };
            });

            // Now that we have cart computed, open preview instead of submitting immediately
            this.state.yuklashPreviewLines = line_vals.map(l => {
                const product = this.state.allProducts.find(p => p.product_id === l.product_id);
                return {
                    product_id: l.product_id,
                    name: product ? product.name : 'Unknown',
                    qty: l.qty,
                    kelish_narxi: l.price_unit,
                    subtotal: l.qty * l.price_unit
                };
            });

            this.recalculateYuklashPreviewTotal();
            this.state.showYuklashPreviewModal = true;
            this.state.loading = false;

        } catch (e) {
            this.state.error = "Tarmoqda xatolik";
            this.state.loading = false;
        }
    }

    recalculateYuklashPreviewTotal() {
        let t = 0;
        for (let l of this.state.yuklashPreviewLines) {
            l.subtotal = l.qty * l.kelish_narxi;
            t += l.subtotal;
        }
        this.state.yuklashPreviewTotal = t;
    }

    updateYuklashPreviewLine(index, field, value) {
        const num = parseFormattedNumber(value);
        if (field === 'qty') {
            this.state.yuklashPreviewLines[index].qty = num;
        } else if (field === 'price') {
            this.state.yuklashPreviewLines[index].kelish_narxi = num;
        }
        this.recalculateYuklashPreviewTotal();
    }

    removeYuklashPreviewLine(index) {
        this.state.yuklashPreviewLines.splice(index, 1);
        this.recalculateYuklashPreviewTotal();
    }

    closeYuklashPreview() {
        this.state.showYuklashPreviewModal = false;
    }

    async confirmYuklash() {
        if (this.state.yuklashPreviewLines.length === 0) {
            this.showToast("Mahsulot qolmadi", "danger");
            return;
        }

        this.state.loading = true;
        try {
            // Re-package the lines based on the preview edits
            const line_vals = this.state.yuklashPreviewLines.map(l => {
                return {
                    product_id: l.product_id,
                    qty: l.qty,
                    price_unit: l.kelish_narxi
                };
            });

            const result = await rpc("/van/pos/submit_trip", {
                taminotchi_id: parseInt(this.state.selectedTaminotchiId),
                agent_id: this.state.currentAgent.id,
                date: this.state.tripDate,
                note: this.state.tripNote,
                lines: line_vals
            });

            if (result.success) {
                this.showToast("Sayohat saqlandi", "success");
                this.state.showYuklashPreviewModal = false;
                this.state.screen = 'trips_list';
                await this.openTripsList();
            } else {
                this.showToast(result.error || "Saqlab bo'lmadi", "danger");
            }
        } catch (e) {
            this.showToast("Tarmoqda xatolik", "danger");
        }
        this.state.loading = false;
    }

    // --- QUICK ACTIONS HISTORY MANAGEMENT ---

    async openPaymentHistory(type) {
        // type: 'kirim' or 'chiqim'
        this.state.paymentHistoryType = type;
        this.state.loading = true;
        try {
            const apiType = type === 'kirim' ? 'in' : 'out';
            const result = await rpc("/van/pos/get_payments", { payment_type: apiType });
            if (result.success) {
                this.state.paymentHistory = result.payments || [];
                this.state.screen = 'payment_history';
            } else {
                this.showToast(result.error || "Tarixni olib bo'lmadi", "danger");
            }
        } catch (e) {
            this.showToast("Tarmoqda xato", "danger");
        }
        this.state.loading = false;
    }

    editPaymentAction(payment) {
        this.state.showKirimClientModal = false;
        this.state.showKirimAmountModal = false;
        this.state.editingPaymentId = payment.id;
        this.state.quickActionType = this.state.paymentHistoryType;
        this.state.quickActionAmount = formatNumberWithCommas(payment.amount);
        this.state.quickActionNote = payment.note || '';
        this.state.quickActionPartnerId = payment.partner_id ? String(payment.partner_id) : '';
        this.state.quickActionExpenseType = payment.expense_type || 'daily';
        this.state.showQuickAction = true;
    }

    async deletePaymentAction(paymentId) {
        if (!confirm("Ushbu yozuvni o'chirmoqchimisiz?")) return;
        this.state.loading = true;
        try {
            const result = await rpc("/van/pos/delete_payment", { payment_id: paymentId });
            if (result.success) {
                this.showToast("O'chirildi", "success");
                await this.openPaymentHistory(this.state.paymentHistoryType);
            } else {
                this.showToast(result.error || "Xatolik", "danger");
            }
        } catch (e) {
            this.showToast("Tarmoq xatosi", "danger");
        }
        this.state.loading = false;
    }

    goBack() {
        if (this.state.screen === 'clients') {
            this.state.screen = 'products';
        } else if (this.state.screen === 'client_report') {
            this.state.clientReport = null;
            this.state.clientReportExpandedRows = {};
            this.state.screen = 'clients';
            this.restoreClientsScroll();
        } else if (this.state.screen === 'checkout') {
            this.state.screen = 'products';
        } else if (this.state.screen === 'requests_list') {
            this.state.screen = 'products';
        } else if (this.state.screen === 'new_request_form') {
            this.state.screen = 'requests_list';
        } else if (this.state.screen === 'request_details') {
            this.state.activeRequest = null;
            this.state.screen = 'requests_list';
        } else if (this.state.screen === 'request_add_product') {
            this.state.screen = 'request_details';
        } else if (this.state.screen === 'trips_list') {
            this.state.screen = 'products';
        } else if (this.state.screen === 'mahsulot_yuklash_form') {
            this.state.screen = 'trips_list';
        } else if (this.state.screen === 'trip_details') {
            this.state.activeTrip = null;
            this.state.screen = 'trips_list';
        }
    }

    // --- CLIENT HISOB-KITOB (REPORT) ---
    async openClientReport(client, event) {
        if (event) event.stopPropagation();
        this.captureClientsScroll();
        this.state.clientReportClientId = client.id;
        this.cancelEdit(event);
        this.state.clientReportDateFrom = '';
        this.state.clientReportDateTo = '';
        this.state.clientReportExpandedRows = {};
        this.state.clientReport = null;
        this.state.screen = 'client_report';
        await this._fetchClientReport(client.id);
    }

    getScrollContainer() {
        return this.el?.querySelector('.van-pos-content');
    }

    captureClientsScroll() {
        const container = this.getScrollContainer();
        if (container) {
            this.state.clientsScrollTop = container.scrollTop || 0;
        }
    }

    restoreClientsScroll() {
        const scrollTop = this.state.clientsScrollTop || 0;
        requestAnimationFrame(() => {
            const container = this.getScrollContainer();
            if (container) {
                container.scrollTop = scrollTop;
            }
        });
    }

    async _fetchClientReport(clientId) {
        this.state.clientReportLoading = true;
        try {
            const result = await rpc('/van/pos/get_client_report', {
                client_id: clientId,
                date_from: this.state.clientReportDateFrom || null,
                date_to: this.state.clientReportDateTo || null,
            });
            if (result.success) {
                this.state.clientReport = result;
                this.state.clientReportTelegramChatId = result.telegram_chat_id || '';
            } else {
                this.showToast(result.error || "Hisobot yuklanmadi", "error");
            }
        } catch (e) {
            this.showToast("Tarmoqda xatolik: Hisobot yuklanmadi", "error");
        }
        this.state.clientReportLoading = false;
    }

    async filterClientReport() {
        if (this.state.clientReportClientId) {
            await this._fetchClientReport(this.state.clientReportClientId);
        }
    }

    clearClientReportFilter() {
        this.state.clientReportDateFrom = '';
        this.state.clientReportDateTo = '';
        this.filterClientReport();
    }

    async saveClientTelegramChatId() {
        if (!this.state.clientReportClientId) {
            return;
        }
        this.state.clientReportTelegramSaving = true;
        try {
            const result = await rpc('/van/pos/update_client_telegram_chat_id', {
                client_id: this.state.clientReportClientId,
                telegram_chat_id: this.state.clientReportTelegramChatId || '',
            });
            if (result.success) {
                if (this.state.clientReport) {
                    this.state.clientReport.telegram_chat_id = result.telegram_chat_id || '';
                }
                this.state.clientReportTelegramChatId = result.telegram_chat_id || '';
                this.showToast(result.message || "Telegram Chat ID saqlandi", "success");
            } else {
                this.showToast(result.error || "Telegram Chat ID saqlanmadi", "error");
            }
        } catch (e) {
            this.showToast("Tarmoqda xatolik: Telegram Chat ID saqlanmadi", "error");
        }
        this.state.clientReportTelegramSaving = false;
    }

    toggleReportRow(index) {
        this.state.clientReportExpandedRows[index] = !this.state.clientReportExpandedRows[index];
    }

    // --- CLIENT HISOB-KITOB EDIT MODE ---
    cancelEdit(event) {
        if (event) event.stopPropagation();
        this.state.editingTxnId = null;
        this.state.editKirimAmount = '';
        this.state.editSotuvLines = {};
    }

    enableEdit(tx, event) {
        if (event) event.stopPropagation();
        this.state.editingTxnId = tx.id;
        if (tx.turi === 'kirim') {
            this.state.editKirimAmount = formatNumberWithCommas(tx.summa);
        } else if (tx.turi === 'sotuv') {
            this.state.editSotuvLines = {};
            for (const line of tx.lines) {
                this.state.editSotuvLines[line.id] = {
                    qty: line.qty,
                    price: line.price,
                    price_formatted: formatNumberWithCommas(line.price)
                };
            }
            // Auto expand the row so they can see inputs
            const idx = this.state.clientReport.transactions.indexOf(tx);
            if (idx >= 0) {
                this.state.clientReportExpandedRows[idx] = true;
            }
        }
    }

    async saveChanges(tx, event) {
        if (event) event.stopPropagation();
        this.state.clientReportLoading = true;

        try {
            if (tx.turi === 'kirim') {
                const amount = parseFormattedNumber(this.state.editKirimAmount);
                if (amount < 0 || isNaN(amount)) {
                    this.showToast("Noto'g'ri summa", "error");
                    this.state.clientReportLoading = false;
                    return;
                }
                const result = await rpc('/van/mijoz/edit-kirim', {
                    payment_id: tx.id,
                    new_amount: amount
                });
                if (result.success) {
                    this.showToast("Saqlandi", "success");
                    this.cancelEdit();
                    await this._fetchClientReport(this.state.clientReportClientId);
                } else {
                    this.showToast(result.error || "Xato", "error");
                }
            } else if (tx.turi === 'sotuv') {
                const linesPayload = [];
                for (const lid in this.state.editSotuvLines) {
                    const lData = this.state.editSotuvLines[lid];
                    if (lData.qty < 0 || lData.price < 0) {
                        this.showToast("Miqdor/Narx manfiy bo'lmaydi", "error");
                        this.state.clientReportLoading = false;
                        return;
                    }
                    linesPayload.push({
                        line_id: lid,
                        qty: lData.qty,
                        price: lData.price
                    });
                }
                const result = await rpc('/van/mijoz/edit-sotuv', {
                    order_id: tx.id,
                    lines: linesPayload
                });
                if (result.success) {
                    this.showToast("Saqlandi", "success");
                    this.cancelEdit();
                    await this._fetchClientReport(this.state.clientReportClientId);
                    this.loadInventorySilent(); // Update local inventory stock
                } else {
                    this.showToast(result.error || "Xato", "error");
                }
            }
        } catch (e) {
            this.showToast("Tarmoq xatosi", "error");
        }
        this.state.clientReportLoading = false;
    }

    async confirmDelete(tx, event) {
        if (event) event.stopPropagation();
        if (!confirm("Haqiqatan ham ushbu yozuvni o'chirmoqchimisiz?")) {
            return;
        }

        this.state.clientReportLoading = true;
        try {
            let result;
            if (tx.turi === 'kirim') {
                result = await rpc('/van/mijoz/delete-kirim', { payment_id: tx.id });
            } else if (tx.turi === 'sotuv') {
                result = await rpc('/van/mijoz/delete-sotuv', { order_id: tx.id });
            }

            if (result && result.success) {
                this.showToast("O'chirildi", "success");
                await this._fetchClientReport(this.state.clientReportClientId);
                if (tx.turi === 'sotuv') {
                    this.loadInventorySilent(); // Return deleted sale stock to inventory natively
                }
            } else {
                this.showToast(result?.error || "O'chirishda xatolik", "error");
            }
        } catch (e) {
            this.showToast("Tarmoq xatosi", "error");
        }
        this.state.clientReportLoading = false;
    }

    openAgentSummary() {
        if (!this.state.currentAgent) {
            this.state.error = "Akkauntingizga agent biriktirilmagan.";
            return;
        }

        // Remove popstate listener briefly so standard Odoo back buttons work
        if (this.popStateHandler) {
            window.removeEventListener('popstate', this.popStateHandler);
        }

        // Directly open the agent summary form view for the current agent
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Agent Hisoboti',
            res_model: 'van.agent.summary',
            res_id: this.state.currentAgent.summary_id,
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'current',
        });
    }

    closePos() {
        if (this.popStateHandler) {
            window.removeEventListener('popstate', this.popStateHandler);
        }
        this.action.doAction({
            type: 'ir.actions.client',
            tag: 'reload',
        });
    }

    logout() {
        window.location.href = '/web/session/logout';
    }

    goToDashboard() {
        this.action.doAction('van_sales_pharma.action_van_sales_dashboard');
    }
}

VanMobilePos.template = "van_sales_pharma.VanMobilePos";
registry.category("actions").add("van_sales_pharma.MobilePosClientAction", VanMobilePos);
