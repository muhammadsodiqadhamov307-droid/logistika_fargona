/** @odoo-module **/

import { session } from "@web/session";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

if (session.is_van_agent) {
    // 1. We rely entirely on the Action Service patch now
    // as modifying location.replace() causes an infinite reload loop in Odoo 19.

    // 3. Patch Action Service to block everything else
    registry.category("services").add("van_agent_locker", {
        dependencies: ["action"],
        start(env, { action }) {
            const originalDoAction = action.doAction.bind(action);
            action.doAction = (actionRequest, options) => {
                // If it's a string, it might be an xml_id
                let actionTag = actionRequest;
                if (typeof actionRequest === 'object' && actionRequest !== null) {
                    actionTag = actionRequest.tag || actionRequest.xml_id;
                }

                // Allow the mobile POS client action, login/logout routes
                // Also explicitly allow the agent to view their own summary form
                let isAllowed = false;
                if (actionRequest === 'van_sales_pharma.action_van_mobile_pos_app' || actionRequest === 'van_sales_pharma.action_van_mobile_pos' || actionRequest === 'van_sales_pharma.action_van_mobile_pos_entry') isAllowed = true;
                if (actionTag === 'van_sales_pharma.MobilePosClientAction' || actionTag === 'reload') isAllowed = true;
                if (actionRequest && actionRequest.res_model === 'van.agent.summary') isAllowed = true;

                if (isAllowed) {
                    return originalDoAction(actionRequest, options);
                }

                // Block everything else and force POS
                console.warn("Blocked agent from opening action:", actionRequest);
                return originalDoAction('van_sales_pharma.action_van_mobile_pos_app', options);
            };
        }
    });

    // 4. Hide the Odoo main navbar completely for agents
    const style = document.createElement('style');
    style.innerHTML = `
        .o_main_navbar { display: none !important; }
        .o_web_client { padding-top: 0 !important; }
        .o_content { overflow: auto !important; height: 100vh !important; }
        /* Notice: Removed blocking of .o_control_panel so the breadcrumb back button is visible on form views */
    `;
    document.head.appendChild(style);
}
