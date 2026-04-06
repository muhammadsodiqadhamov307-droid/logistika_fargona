/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { loadJS } from "@web/core/assets";

export class VanSalesDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.chartRef = useRef("monthlySalesChart");
        this.chartInstance = null;

        this.state = useState({
            today_trips_count: 0,
            active_trips_count: 0,
            total_cash: 0,
            total_card: 0,
            total_chiqim: 0,
            total_nasiya: 0,
            total_taminotchi_balance: 0,
            jami: 0,
            sof_foyda: 0,
            margin_today: 0,
            top_customers: [],
            top_agents: [],
            top_products: [],
            chart_labels: [],
            chart_data: [],
            detail_view_id: false,
            margin_view_id: false,
            currency_id: false,
            date_from: false,
            date_to: false,
        });

        onWillStart(async () => {
            await this.fetchDashboardData();
        });

        onMounted(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.renderChart();
        });
    }

    async fetchDashboardData() {
        const kwargs = {};
        if (this.state.date_from) kwargs.date_from = this.state.date_from;
        if (this.state.date_to) kwargs.date_to = this.state.date_to;

        const data = await this.orm.call("van.trip", "get_van_dashboard_data", [], kwargs);
        this.state.today_trips_count = data.today_trips_count;
        this.state.active_trips_count = data.active_trips_count;
        this.state.total_cash = data.total_cash;
        this.state.total_card = data.total_card;
        this.state.total_chiqim = data.total_chiqim || 0;
        this.state.total_nasiya = data.total_global_nasiya;
        this.state.total_taminotchi_balance = data.total_taminotchi_balance || 0;
        this.state.jami = data.jami || 0;
        this.state.sof_foyda = data.sof_foyda || 0;
        this.state.margin_today = data.margin_today || 0;
        this.state.top_customers = data.top_customers;
        this.state.top_agents = data.top_agents;
        this.state.top_products = data.top_products;
        this.state.chart_labels = data.chart_labels;
        this.state.chart_data = data.chart_data;
        this.state.detail_view_id = data.detail_view_id;
        this.state.margin_view_id = data.margin_view_id;
        this.state.currency_id = data.currency_id;
    }

    renderChart() {
        if (!this.chartRef.el) return;

        if (this.chartInstance) {
            this.chartInstance.destroy();
        }

        const ctx = this.chartRef.el.getContext('2d');
        this.chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: this.state.chart_labels,
                datasets: [{
                    label: 'Oylik Sof Tushum',
                    data: this.state.chart_data,
                    backgroundColor: 'rgba(13, 202, 240, 0.2)', // Bootstrap info transparent
                    borderColor: 'rgba(13, 202, 240, 1)',
                    borderWidth: 2,
                    pointBackgroundColor: '#0bacce',
                    pointRadius: 4,
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: (value) => {
                                return value.toLocaleString() + ' So\'m'; // Fallback if formatMonetary is complex here
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });
    }

    async applyFilter() {
        await this.fetchDashboardData();
        this.renderChart();
    }

    async clearFilter() {
        this.state.date_from = false;
        this.state.date_to = false;
        await this.fetchDashboardData();
        this.renderChart();
    }

    formatPrice(amount) {
        return formatMonetary(amount, {
            currencyId: this.state.currency_id,
        });
    }

    openTrips() {
        const today = new Date().toISOString().slice(0, 10);
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: `Bugungi Sotuvlar`,
            res_model: 'van.pos.order',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['date', '>=', today + ' 00:00:00']],
            target: 'current',
        });
    }

    openMarginDetails() {
        let domain = [['order_id.state', '=', 'done']];
        if (this.state.date_from) {
            domain.push(['order_id.date', '>=', this.state.date_from + ' 00:00:00']);
        }
        if (this.state.date_to) {
            domain.push(['order_id.date', '<=', this.state.date_to + ' 23:59:59']);
        }
        if (!this.state.date_from && !this.state.date_to) {
            const today = new Date().toISOString().slice(0, 10);
            domain.push(['order_id.date', '>=', today + ' 00:00:00']);
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: `Foyda Detallari`,
            res_model: 'van.pos.order.line',
            view_mode: 'list,form',
            views: [[this.state.margin_view_id, 'list'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }

    openSales() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: `Sotuvlar Detallari`,
            res_model: 'van.pos.order.line',
            view_mode: 'list',
            views: [[false, 'list']],
            target: 'current',
        });
    }

    openSale(saleId) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'van.pos.order',
            res_id: saleId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openSalesByMethod(method) {
        // Nasiya has its own dedicated model - open it directly
        if (method === 'nasiya') {
            this.action.doAction({
                type: 'ir.actions.act_window',
                name: 'Jami Nasiyalar',
                res_model: 'van.nasiya',
                view_mode: 'list,form',
                views: [[false, 'list'], [false, 'form']],
                target: 'current',
            });
            return;
        }

        // Cash = Actual van.payment (kirim) AND Naqt savdo (POS sales with partner_id = False)
        if (method === 'cash') {
            let cashDomain = [
                '|',
                '&', ['transaction_type', '=', 'kirim'], ['payment_method', '=', 'cash'],
                '&', ['transaction_type', '=', 'sale'], ['partner_id', '=', false]
            ];

            if (this.state.date_from) cashDomain.push(['date', '>=', this.state.date_from + ' 00:00:00']);
            if (this.state.date_to) cashDomain.push(['date', '<=', this.state.date_to + ' 23:59:59']);

            this.action.doAction({
                type: 'ir.actions.act_window',
                name: 'Naqt Pul Amaliyotlari',
                res_model: 'van.dashboard.detail',
                view_mode: 'list,form',
                views: [[false, 'list'], [false, 'form']],
                domain: cashDomain,
                target: 'current',
            });
            return;
        }

        // Chiqim = go to the Chiqimlar menu directly
        if (method === 'chiqim') {
            this.action.doAction('van_sales_pharma.action_van_chiqimlar_global');
            return;
        }

        let domain = [];
        if (this.state.date_from) {
            domain.push(['date', '>=', this.state.date_from + ' 00:00:00']);
        }
        if (this.state.date_to) {
            domain.push(['date', '<=', this.state.date_to + ' 23:59:59']);
        }

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Amaliyotlar',
            res_model: 'van.dashboard.detail',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }

    openTaminotchilar() {
        this.action.doAction('van_sales_pharma.action_van_taminotchi');
    }

}

VanSalesDashboard.template = "van_sales_pharma.DashboardView";
registry.category("actions").add("van_sales_dashboard_action", VanSalesDashboard);
