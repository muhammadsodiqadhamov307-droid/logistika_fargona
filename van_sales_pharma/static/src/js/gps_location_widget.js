/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * GpsCaptureWidget — field widget bound to x_latitude.
 * Reads both x_latitude and x_longitude from the record,
 * provides a GPS capture button and a Google Maps link.
 */
class GpsCaptureWidget extends Component {
    static template = "van_sales_pharma.GpsCaptureWidget";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({ loading: false, error: null });
    }

    get latitude() {
        return this.props.record.data.x_latitude || 0;
    }

    get longitude() {
        return this.props.record.data.x_longitude || 0;
    }

    get hasLocation() {
        return Math.abs(this.latitude) > 0.0001 || Math.abs(this.longitude) > 0.0001;
    }

    get googleMapsUrl() {
        if (!this.hasLocation) return "";
        return `https://www.google.com/maps?q=${this.latitude},${this.longitude}`;
    }

    get coordsLabel() {
        if (!this.hasLocation) return "";
        return `${this.latitude.toFixed(5)}, ${this.longitude.toFixed(5)}`;
    }

    async captureLocation() {
        if (!navigator.geolocation) {
            this.state.error = "Brauzeringiz GPS ni qo'llab-quvvatlamaydi.";
            return;
        }
        this.state.loading = true;
        this.state.error = null;
        navigator.geolocation.getCurrentPosition(
            async (pos) => {
                try {
                    await this.props.record.update({
                        x_latitude: parseFloat(pos.coords.latitude.toFixed(7)),
                        x_longitude: parseFloat(pos.coords.longitude.toFixed(7)),
                    });
                } finally {
                    this.state.loading = false;
                }
            },
            () => {
                this.state.error = "GPS ruxsat berilmadi yoki xatolik yuz berdi.";
                this.state.loading = false;
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    }

    openGoogleMaps() {
        const url = this.googleMapsUrl;
        if (url) {
            window.open(url, "_blank");
        }
    }
}

registry.category("fields").add("gps_capture", GpsCaptureWidget);
