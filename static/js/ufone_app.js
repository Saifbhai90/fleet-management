/**
 * Ufone BPOCOPS Portal - Shared JavaScript Utilities
 * Dark mode, animated counters, AJAX wrapper, map helpers, DataTables config
 */

const UfoneCore = (function() {
    'use strict';
    
    // Dark mode
    const initDarkMode = function() {
        const toggle = document.getElementById('darkModeToggle');
        if (!toggle) return;
        
        // Load saved preference
        const savedTheme = localStorage.getItem('ufone-theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        
        toggle.addEventListener('click', function() {
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('ufone-theme', next);
        });
    };
    
    // Animated counter
    const animateCounter = function(element, target, duration = 1000) {
        if (!element) return;
        
        const start = 0;
        const increment = target / (duration / 16);
        let current = start;
        
        const timer = setInterval(function() {
            current += increment;
            if (current >= target) {
                element.textContent = target.toLocaleString();
                clearInterval(timer);
            } else {
                element.textContent = Math.floor(current).toLocaleString();
            }
        }, 16);
    };
    
    // AJAX wrapper with CSRF + error toast
    const ajax = function(options) {
        const defaults = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            error: function(xhr, status, error) {
                showToast('Request failed: ' + (xhr.responseJSON?.message || error), 'error');
            }
        };
        
        const settings = Object.assign({}, defaults, options);
        
        return $.ajax(settings);
    };
    
    // Get CSRF token
    const getCsrfToken = function() {
        return $('meta[name="csrf-token"]').attr('content') || '';
    };
    
    // Show toast message
    const showToast = function(message, type = 'info') {
        const toast = $(`
            <div class="ufone-toast ${type}">
                <div class="toast-content">${message}</div>
                <button class="toast-close">&times;</button>
            </div>
        `);
        
        $('body').append(toast);
        
        toast.find('.toast-close').on('click', function() {
            toast.remove();
        });
        
        setTimeout(function() {
            toast.remove();
        }, 5000);
    };
    
    // Live map helper (Leaflet)
    const initMap = function(mapId, options = {}) {
        const defaults = {
            center: [30.3753, 69.3451], // Pakistan center
            zoom: 6,
            darkMode: document.documentElement.getAttribute('data-theme') === 'dark'
        };
        
        const settings = Object.assign({}, defaults, options);
        
        const map = L.map(mapId, {
            center: settings.center,
            zoom: settings.zoom
        });
        
        // Tile layer
        const tileUrl = settings.darkMode
            ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
            : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
        
        L.tileLayer(tileUrl, {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(map);
        
        return map;
    };
    
    // Add ambulance marker
    const addAmbulanceMarker = function(map, ambulance, options = {}) {
        const statusColors = {
            'Moving': '#10b981',
            'Stopped': '#ef4444',
            'Idle': '#f59e0b',
            'Offline': '#6b7280'
        };
        
        const color = statusColors[ambulance.status] || '#6b7280';
        
        // Custom marker icon
        const icon = L.divIcon({
            className: 'ambulance-marker',
            html: `
                <svg width="32" height="32" viewBox="0 0 32 32">
                    <circle cx="16" cy="16" r="12" fill="${color}" stroke="white" stroke-width="2"/>
                    <text x="16" y="20" text-anchor="middle" fill="white" font-size="10">🚑</text>
                </svg>
            `,
            iconSize: [32, 32],
            iconAnchor: [16, 16]
        });
        
        const marker = L.marker([ambulance.lat, ambulance.lon], { icon: icon });
        
        // Popup
        const popupContent = `
            <div class="ambulance-popup">
                <strong>${ambulance.reg_no}</strong><br>
                Status: ${ambulance.status}<br>
                Driver: ${ambulance.driver_name || 'N/A'}<br>
                Location: ${ambulance.location || 'N/A'}<br>
                Last Update: ${ambulance.last_update || 'N/A'}
            </div>
        `;
        
        marker.bindPopup(popupContent);
        
        if (options.onClick) {
            marker.on('click', options.onClick);
        }
        
        marker.addTo(map);
        return marker;
    };
    
    // DataTables config preset
    const dataTableConfig = function(options = {}) {
        const defaults = {
            responsive: true,
            pageLength: 25,
            lengthMenu: [[10, 25, 50, 100], [10, 25, 50, 100]],
            language: {
                search: "_INPUT_",
                searchPlaceholder: "Search..."
            },
            dom: '<"top"f>rt<"bottom"ip><"clear">',
            order: []
        };
        
        return Object.assign({}, defaults, options);
    };
    
    // Auto-refresh timer with countdown
    const initAutoRefresh = function(callback, interval = 30000) {
        let timer = null;
        let countdown = interval / 1000;
        let isRunning = false;
        
        const updateCountdown = function() {
            const indicator = document.getElementById('refreshCountdown');
            if (indicator) {
                indicator.textContent = countdown + 's';
            }
        };
        
        const start = function() {
            if (isRunning) return;
            isRunning = true;
            
            countdown = interval / 1000;
            updateCountdown();
            
            timer = setInterval(function() {
                countdown--;
                updateCountdown();
                
                if (countdown <= 0) {
                    countdown = interval / 1000;
                    callback();
                }
            }, 1000);
        };
        
        const stop = function() {
            if (!isRunning) return;
            isRunning = false;
            
            if (timer) {
                clearInterval(timer);
                timer = null;
            }
            
            const indicator = document.getElementById('refreshCountdown');
            if (indicator) {
                indicator.textContent = 'Stopped';
            }
        };
        
        const refreshNow = function() {
            countdown = interval / 1000;
            callback();
        };
        
        return {
            start: start,
            stop: stop,
            refreshNow: refreshNow,
            isRunning: function() { return isRunning; }
        };
    };
    
    // Skeleton loader helpers
    const showSkeleton = function(container, count = 5) {
        let html = '';
        for (let i = 0; i < count; i++) {
            html += `
                <div class="skeleton-row">
                    <div class="skeleton" style="width: 30%; height: 20px;"></div>
                    <div class="skeleton" style="width: 50%; height: 20px;"></div>
                    <div class="skeleton" style="width: 20%; height: 20px;"></div>
                </div>
            `;
        }
        container.innerHTML = html;
    };
    
    const hideSkeleton = function(container, content) {
        container.innerHTML = content;
    };
    
    // Format date
    const formatDate = function(dateStr, format = 'YYYY-MM-DD HH:mm') {
        if (!dateStr) return 'N/A';
        
        const date = new Date(dateStr);
        
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        
        return format
            .replace('YYYY', year)
            .replace('MM', month)
            .replace('DD', day)
            .replace('HH', hours)
            .replace('mm', minutes)
            .replace('ss', seconds);
    };
    
    // Format number
    const formatNumber = function(num, decimals = 0) {
        if (num === null || num === undefined) return 'N/A';
        return Number(num).toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    };
    
    // Initialize all
    const init = function() {
        initDarkMode();
        
        // Animate all counters on page load
        document.querySelectorAll('.animated-counter').forEach(function(el) {
            const target = parseInt(el.textContent.replace(/,/g, '')) || 0;
            animateCounter(el, target);
        });
    };
    
    // Public API
    return {
        init: init,
        animateCounter: animateCounter,
        ajax: ajax,
        showToast: showToast,
        initMap: initMap,
        addAmbulanceMarker: addAmbulanceMarker,
        dataTableConfig: dataTableConfig,
        initAutoRefresh: initAutoRefresh,
        showSkeleton: showSkeleton,
        hideSkeleton: hideSkeleton,
        formatDate: formatDate,
        formatNumber: formatNumber
    };
})();

// Initialize on DOM ready
$(document).ready(function() {
    UfoneCore.init();
});
