/**
 * LionByteGG Dashboard JavaScript Utilities
 */

// Toast Notification System
class ToastManager {
    constructor() {
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        // Inline fixed positioning so it never participates in body flex layout
        this.container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:10px;max-width:380px;pointer-events:none;contain:layout style paint;';
        document.body.appendChild(this.container);
    }

    show(type, title, message, duration = 5000) {
        const toast = document.createElement('div');
        toast.className = 'toast ' + type + ' fade-in';
        
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-times-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };

        toast.innerHTML = '<div class="toast-icon"><i class="fas ' + icons[type] + '"></i></div>' +
            '<div class="toast-content"><div class="toast-title">' + title + '</div>' +
            '<div class="toast-message">' + message + '</div></div>' +
            '<button class="toast-close" onclick="this.parentElement.remove()"><i class="fas fa-times"></i></button>';

        this.container.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => {
                toast.style.animation = 'slideOut 0.3s ease forwards';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }

        return toast;
    }

    success(title, message, duration) {
        return this.show('success', title, message, duration);
    }

    error(title, message, duration) {
        return this.show('error', title, message, duration);
    }

    warning(title, message, duration) {
        return this.show('warning', title, message, duration);
    }

    info(title, message, duration) {
        return this.show('info', title, message, duration);
    }
}

// Initialize toast manager
const toast = new ToastManager();

// API Helper
class API {
    static async get(endpoint) {
        try {
            const response = await fetch(endpoint);
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return await response.json();
        } catch (error) {
            console.error('API GET ' + endpoint + ' failed:', error);
            throw error;
        }
    }

    static async post(endpoint, data = {}) {
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return await response.json();
        } catch (error) {
            console.error('API POST ' + endpoint + ' failed:', error);
            throw error;
        }
    }
}

// Utility Functions
const Utils = {
    timeAgo(date) {
        const seconds = Math.floor((new Date() - date) / 1000);
        const intervals = {
            year: 31536000,
            month: 2592000,
            week: 604800,
            day: 86400,
            hour: 3600,
            minute: 60
        };
        
        for (const [unit, secondsInUnit] of Object.entries(intervals)) {
            const interval = Math.floor(seconds / secondsInUnit);
            if (interval >= 1) {
                return interval + ' ' + unit + (interval > 1 ? 's' : '') + ' ago';
            }
        }
        return 'Just now';
    },

    formatNumber(num) {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    },

    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            console.error('Failed to copy:', err);
            return false;
        }
    },

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    async confirm(message) {
        return window.confirm(message);
    },

    getInitials(name) {
        return name
            .split(' ')
            .map(word => word[0])
            .join('')
            .toUpperCase()
            .slice(0, 2);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Loading State Manager
class LoadingState {
    static show(element, text = 'Loading...') {
        element.dataset.originalContent = element.innerHTML;
        element.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; gap: 10px; padding: 20px;">' +
            '<div class="loading-spinner"></div><span>' + text + '</span></div>';
        element.classList.add('loading');
    }

    static hide(element) {
        if (element.dataset.originalContent) {
            element.innerHTML = element.dataset.originalContent;
            delete element.dataset.originalContent;
        }
        element.classList.remove('loading');
    }
}

// Modal Manager
class ModalManager {
    static open(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
    }

    static close(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    }

    static closeAll() {
        document.querySelectorAll('.modal-overlay.active').forEach(modal => {
            modal.classList.remove('active');
        });
        document.body.style.overflow = '';
    }
}

// Close modals on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        ModalManager.closeAll();
    }
});

// Close modals on overlay click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        ModalManager.closeAll();
    }
});

// Auto-refresh functionality
class AutoRefresh {
    constructor(callback, interval = 30000) {
        this.callback = callback;
        this.interval = interval;
        this.timer = null;
    }

    start() {
        this.stop();
        this.timer = setInterval(this.callback, this.interval);
    }

    stop() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }
}

// Export for use in templates
window.LionByte = {
    toast,
    API,
    Utils,
    LoadingState,
    ModalManager,
    AutoRefresh
};

// ============================================
// MASTER DIAGNOSTICS CONSOLE
// ============================================

class SystemDiagnostics {
    constructor() {
        this.isOpen = false;
        this.testResults = {};
        this.startTime = null;
        this.testCount = 0;
        this.verbose = false;
        
        // Deep-scan pacing + control state
        this.deepMode = true;
        this.cadenceMs = 4500;      // paced cadence per test on a Full Deep Scan (~10+ min total)
        this.samples = 3;           // latency samples per network test in deep mode
        this.reqTimeoutMs = 12000;  // per-request timeout so a hung service can't stall the run
        this.running = false;
        this.cancelRequested = false;
        this.plannedTotal = 0;
        this.completedCount = 0;

        // Category order + presentation (drives the sidebar, sections, and run order)
        this.categoryMeta = [
            { id: 'system',      icon: 'fa-microchip',        title: 'System Health' },
            { id: 'auth',        icon: 'fa-shield-alt',       title: 'Authentication & Access' },
            { id: 'bot',         icon: 'fa-robot',            title: 'Discord Bot Core' },
            { id: 'novaPages',   icon: 'fa-window-maximize',  title: 'Nova Pages' },
            { id: 'api',         icon: 'fa-plug',             title: 'Nova Core APIs' },
            { id: 'management',  icon: 'fa-users-cog',        title: 'Management APIs' },
            { id: 'moderation',  icon: 'fa-gavel',            title: 'Moderation' },
            { id: 'equipment',   icon: 'fa-toolbox',          title: 'Equipment & On-Duty' },
            { id: 'rosters',     icon: 'fa-trophy',           title: 'Rosters & Teams' },
            { id: 'tickets',     icon: 'fa-ticket-alt',       title: 'Support Tickets' },
            { id: 'shifts',      icon: 'fa-calendar-alt',     title: 'LionShift System' },
            { id: 'music',       icon: 'fa-music',            title: 'LionBeats Music' },
            { id: 'boilercraft', icon: 'fa-cube',             title: 'BoilerCraft' },
            { id: 'arena',       icon: 'fa-gamepad',          title: 'Arena & Kiosks' },
            { id: 'external',    icon: 'fa-cloud',            title: 'External Services' },
            { id: 'ui',          icon: 'fa-desktop',          title: 'UI & Frontend' },
            { id: 'performance', icon: 'fa-tachometer-alt',   title: 'Performance' }
        ];

        this.testDefinitions = {
            system: [
                { id: 'sys-health', name: 'Server Health', endpoint: '/health', desc: 'GET /health' },
                { id: 'sys-ping', name: 'Server Ping', endpoint: '/health', desc: 'Response time check', type: 'ping' },
                { id: 'sys-memory', name: 'Browser Memory', desc: 'Check memory usage', type: 'browser-memory' },
                { id: 'sys-storage', name: 'Local Storage', desc: 'Check storage availability', type: 'storage' }
            ],
            auth: [
                { id: 'auth-session', name: 'Session Status', endpoint: '/api/auth/user', desc: 'Check active session', type: 'session' },
                { id: 'auth-user', name: 'User Info API', endpoint: '/api/auth/user', desc: 'GET /api/auth/user' },
                { id: 'auth-permissions', name: 'Permissions API', endpoint: '/api/auth/permissions', desc: 'GET /api/auth/permissions' },
                { id: 'auth-admin-users', name: 'Admin Users', endpoint: '/api/admin/users', desc: 'GET /api/admin/users' },
                { id: 'auth-admin-groups', name: 'Permission Groups', endpoint: '/api/admin/groups', desc: 'GET /api/admin/groups' },
                { id: 'auth-admin-perms', name: 'Permission Catalog', endpoint: '/api/admin/permissions', desc: 'GET /api/admin/permissions' },
                { id: 'auth-login', name: 'Login Page', endpoint: '/login', desc: 'GET /login' },
                { id: 'auth-admin-page', name: 'Admin Page', endpoint: '/admin', desc: 'GET /admin' }
            ],
            bot: [
                { id: 'bot-stats', name: 'Bot Statistics', endpoint: '/api/stats', desc: 'GET /api/stats' },
                { id: 'bot-activity', name: 'Bot Activity', endpoint: '/api/bot/activity', desc: 'GET /api/bot/activity' },
                { id: 'bot-commands', name: 'Bot Commands', endpoint: '/api/commands', desc: 'GET /api/commands' }
            ],
            novaPages: [
                { id: 'page-root', name: 'Root / Redirect', endpoint: '/', desc: 'GET /' },
                { id: 'page-home', name: 'Home', endpoint: '/home', desc: 'GET /home' },
                { id: 'page-dashboard', name: 'Dashboard', endpoint: '/dashboard', desc: 'GET /dashboard' },
                { id: 'page-moderation', name: 'Moderation Page', endpoint: '/moderation', desc: 'GET /moderation' },
                { id: 'page-users', name: 'Users Page', endpoint: '/users', desc: 'GET /users' },
                { id: 'page-tickets', name: 'Tickets Page', endpoint: '/tickets', desc: 'GET /tickets' },
                { id: 'page-settings', name: 'Settings Page', endpoint: '/settings', desc: 'GET /settings' },
                { id: 'page-logs', name: 'Logs Page', endpoint: '/logs', desc: 'GET /logs' },
                { id: 'page-members', name: 'Members Page', endpoint: '/members', desc: 'GET /members' },
                { id: 'page-varsity', name: 'Varsity Page', endpoint: '/varsity', desc: 'GET /varsity' },
                { id: 'page-analytics', name: 'Analytics Page', endpoint: '/analytics', desc: 'GET /analytics' },
                { id: 'page-reaction-roles', name: 'Reaction Roles Page', endpoint: '/reaction-roles', desc: 'GET /reaction-roles' },
                { id: 'page-vc', name: 'VC System Page', endpoint: '/vc-system', desc: 'GET /vc-system' },
                { id: 'page-rosters', name: 'Rosters Page', endpoint: '/rosters', desc: 'GET /rosters' },
                { id: 'page-onduty', name: 'On-Duty Dashboard', endpoint: '/onduty/dashboard', desc: 'GET /onduty/dashboard' },
                { id: 'page-equipment', name: 'Equipment Page', endpoint: '/onduty/equipment', desc: 'GET /onduty/equipment' }
            ],
            api: [
                { id: 'api-logs', name: 'Bot Logs', endpoint: '/api/logs', desc: 'GET /api/logs' },
                { id: 'api-activity-log', name: 'Activity Log', endpoint: '/api/activity-log', desc: 'GET /api/activity-log' },
                { id: 'api-activity-stats', name: 'Activity Log Stats', endpoint: '/api/activity-log/stats', desc: 'GET /api/activity-log/stats' },
                { id: 'api-analytics', name: 'Analytics API', endpoint: '/api/analytics', desc: 'GET /api/analytics' },
                { id: 'api-search', name: 'Search API', endpoint: '/api/search?query=test', desc: 'GET /api/search' },
                { id: 'api-members', name: 'Members API', endpoint: '/api/members', desc: 'GET /api/members' },
                { id: 'api-channels', name: 'Discord Channels', endpoint: '/api/discord/channels', desc: 'GET /api/discord/channels' },
                { id: 'api-user-records', name: 'User Records', endpoint: '/api/user-records', desc: 'GET /api/user-records' },
                { id: 'api-guests', name: 'Guests API', endpoint: '/api/guests', desc: 'GET /api/guests' },
                { id: 'api-notifications', name: 'Live Notifications', endpoint: '/api/live-notifications', desc: 'GET /api/live-notifications' },
                { id: 'api-jobs', name: 'Background Jobs', endpoint: '/api/jobs/progress', desc: 'GET /api/jobs/progress' }
            ],
            management: [
                { id: 'mgmt-varsity', name: 'Varsity Registrations', endpoint: '/api/varsity-registrations', desc: 'GET /api/varsity-registrations' },
                { id: 'mgmt-reaction-roles', name: 'Reaction Roles API', endpoint: '/api/reaction-roles', desc: 'GET /api/reaction-roles' },
                { id: 'mgmt-vc', name: 'VC Generators', endpoint: '/api/vc-generators', desc: 'GET /api/vc-generators' },
                { id: 'mgmt-vc-live', name: 'VC Generators (Live)', endpoint: '/api/vc-generators/live', desc: 'GET /api/vc-generators/live' },
                { id: 'mgmt-team-roles', name: 'Team Roles', endpoint: '/api/settings/team-roles', desc: 'GET /api/settings/team-roles' },
                { id: 'mgmt-games', name: 'Games Config', endpoint: '/api/settings/games', desc: 'GET /api/settings/games' },
                { id: 'mgmt-arena-hours', name: 'Arena Hours', endpoint: '/api/arena-hours', desc: 'GET /api/arena-hours' }
            ],
            moderation: [
                { id: 'mod-templates', name: 'Moderation Templates', endpoint: '/api/moderation/templates', desc: 'GET /api/moderation/templates' },
                { id: 'mod-watchlist', name: 'Watchlist', endpoint: '/api/watchlist', desc: 'GET /api/watchlist' },
                { id: 'mod-flagged', name: 'Flagged Words', endpoint: '/api/flagged-words', desc: 'GET /api/flagged-words' }
            ],
            equipment: [
                { id: 'eq-list', name: 'Equipment List', endpoint: '/api/equipment', desc: 'GET /api/equipment' },
                { id: 'eq-history', name: 'Equipment History', endpoint: '/api/equipment/history', desc: 'GET /api/equipment/history' },
                { id: 'eq-export', name: 'Equipment Export', endpoint: '/api/equipment/export', desc: 'GET /api/equipment/export' },
                { id: 'eq-qr', name: 'Equipment QR Codes', endpoint: '/api/equipment/qrcodes', desc: 'GET /api/equipment/qrcodes' }
            ],
            rosters: [
                { id: 'roster-list', name: 'Rosters List', endpoint: '/api/rosters', desc: 'GET /api/rosters' },
                { id: 'roster-captains', name: 'Captains', endpoint: '/api/rosters/captains', desc: 'GET /api/rosters/captains' },
                { id: 'roster-audit', name: 'Audit Log', endpoint: '/api/rosters/audit-log', desc: 'GET /api/rosters/audit-log' },
                { id: 'roster-matches', name: 'Match History', endpoint: '/api/rosters/matches', desc: 'GET /api/rosters/matches' },
                { id: 'roster-leaderboard', name: 'Leaderboard', endpoint: '/api/rosters/leaderboard', desc: 'GET /api/rosters/leaderboard' },
                { id: 'roster-announcements', name: 'Announcements', endpoint: '/api/rosters/announcements', desc: 'GET /api/rosters/announcements' },
                { id: 'roster-notifications', name: 'Notification Settings', endpoint: '/api/rosters/notification-settings', desc: 'GET /api/rosters/notification-settings' },
                { id: 'roster-export', name: 'Rosters CSV Export', endpoint: '/api/rosters/export/csv', desc: 'GET /api/rosters/export/csv' }
            ],
            tickets: [
                { id: 'tk-list', name: 'Tickets API', endpoint: '/api/tickets', desc: 'GET /api/tickets' }
            ],
            shifts: [
                { id: 'shift-page-dash', name: 'Shift Dashboard', endpoint: '/lionshift/dashboard', desc: 'GET /lionshift/dashboard' },
                { id: 'shift-page-cal', name: 'Shift Calendar', endpoint: '/lionshift/calendar', desc: 'GET /lionshift/calendar' },
                { id: 'shift-page-sched', name: 'Schedules Page', endpoint: '/lionshift/schedules', desc: 'GET /lionshift/schedules' },
                { id: 'shift-page-workers', name: 'Workers Page', endpoint: '/lionshift/workers', desc: 'GET /lionshift/workers' },
                { id: 'shift-page-activity', name: 'Shift Activity', endpoint: '/lionshift/activity', desc: 'GET /lionshift/activity' },
                { id: 'shift-page-offers', name: 'Offers Page', endpoint: '/lionshift/offers', desc: 'GET /lionshift/offers' },
                { id: 'shift-page-trades', name: 'Trades Page', endpoint: '/lionshift/trades', desc: 'GET /lionshift/trades' },
                { id: 'shift-page-timeoff', name: 'Time Off Page', endpoint: '/lionshift/timeoff', desc: 'GET /lionshift/timeoff' },
                { id: 'shift-page-logs', name: 'Shift Logs Page', endpoint: '/lionshift/logs', desc: 'GET /lionshift/logs' },
                { id: 'shift-page-tasks', name: 'Tasks Page', endpoint: '/lionshift/tasks', desc: 'GET /lionshift/tasks' },
                { id: 'shift-page-settings', name: 'Bot Settings Page', endpoint: '/lionshift/bot-settings', desc: 'GET /lionshift/bot-settings' },
                { id: 'shift-page-creator', name: 'Schedule Creator', endpoint: '/lionshift/schedule-creator', desc: 'GET /lionshift/schedule-creator' },
                { id: 'shift-stats', name: 'Shift Statistics', endpoint: '/api/lionshift/stats', desc: 'GET /api/lionshift/stats' },
                { id: 'shift-schedules', name: 'Schedules API', endpoint: '/api/lionshift/schedules', desc: 'GET /api/lionshift/schedules' },
                { id: 'shift-workers', name: 'Workers API', endpoint: '/api/lionshift/workers', desc: 'GET /api/lionshift/workers' },
                { id: 'shift-offers', name: 'Offers API', endpoint: '/api/lionshift/offers', desc: 'GET /api/lionshift/offers' },
                { id: 'shift-trades', name: 'Trades API', endpoint: '/api/lionshift/trades', desc: 'GET /api/lionshift/trades' },
                { id: 'shift-timeoff', name: 'Time Off API', endpoint: '/api/lionshift/timeoff', desc: 'GET /api/lionshift/timeoff' },
                { id: 'shift-logs', name: 'Shift Logs API', endpoint: '/api/lionshift/logs', desc: 'GET /api/lionshift/logs' },
                { id: 'shift-hours', name: 'Worker Hours', endpoint: '/api/lionshift/worker-hours', desc: 'GET /api/lionshift/worker-hours' },
                { id: 'shift-avail', name: 'Availability', endpoint: '/api/lionshift/availability', desc: 'GET /api/lionshift/availability' },
                { id: 'shift-duties', name: 'Shift Duties', endpoint: '/api/lionshift/shift-duties', desc: 'GET /api/lionshift/shift-duties' },
                { id: 'shift-bot-settings', name: 'Bot Settings API', endpoint: '/api/lionshift/bot-settings', desc: 'GET /api/lionshift/bot-settings' }
            ],
            music: [
                { id: 'music-page-dash', name: 'Music Dashboard', endpoint: '/music/dashboard', desc: 'GET /music/dashboard' },
                { id: 'music-page-now', name: 'Now Playing', endpoint: '/music/nowplaying', desc: 'GET /music/nowplaying' },
                { id: 'music-page-settings', name: 'Music Settings Page', endpoint: '/music/settings', desc: 'GET /music/settings' },
                { id: 'music-page-features', name: 'Music Features', endpoint: '/music/features', desc: 'GET /music/features' },
                { id: 'music-status', name: 'Music Bot Status', endpoint: '/api/music/status', desc: 'GET /api/music/status' },
                { id: 'music-top', name: 'Top Tracks', endpoint: '/api/music/top-tracks', desc: 'GET /api/music/top-tracks' },
                { id: 'music-recent', name: 'Recent Activity', endpoint: '/api/music/recent-activity', desc: 'GET /api/music/recent-activity' },
                { id: 'music-history', name: 'Play History', endpoint: '/api/music/history', desc: 'GET /api/music/history' },
                { id: 'music-stats', name: 'Music Statistics', endpoint: '/api/music/stats', desc: 'GET /api/music/stats' },
                { id: 'music-quiz', name: 'Quiz Songs', endpoint: '/api/music/quiz/songs', desc: 'GET /api/music/quiz/songs' },
                { id: 'music-panels', name: 'Music Panels', endpoint: '/api/music/panels', desc: 'GET /api/music/panels' },
                { id: 'music-settings-api', name: 'Music Settings API', endpoint: '/api/music/settings', desc: 'GET /api/music/settings' },
                { id: 'music-commands', name: 'Music Commands', endpoint: '/api/music/commands', desc: 'GET /api/music/commands' }
            ],
            boilercraft: [
                { id: 'bc-page-dash', name: 'BoilerCraft Dashboard', endpoint: '/boilercraft/dashboard', desc: 'GET /boilercraft/dashboard' },
                { id: 'bc-page-faq', name: 'FAQ Page', endpoint: '/boilercraft/faq', desc: 'GET /boilercraft/faq' },
                { id: 'bc-page-verified', name: 'Verified Players Page', endpoint: '/boilercraft/verified-players', desc: 'GET /boilercraft/verified-players' },
                { id: 'bc-page-watch', name: 'BoilerWatch Page', endpoint: '/boilercraft/boilerwatch', desc: 'GET /boilercraft/boilerwatch' },
                { id: 'bc-page-members', name: 'Members Page', endpoint: '/boilercraft/members', desc: 'GET /boilercraft/members' },
                { id: 'bc-page-analytics', name: 'Analytics Page', endpoint: '/boilercraft/analytics', desc: 'GET /boilercraft/analytics' },
                { id: 'bc-status', name: 'Server Status', endpoint: '/api/boilercraft/server-status', desc: 'GET /api/boilercraft/server-status' },
                { id: 'bc-tickets', name: 'Tickets API', endpoint: '/api/boilercraft/tickets', desc: 'GET /api/boilercraft/tickets' },
                { id: 'bc-settings', name: 'Settings API', endpoint: '/api/boilercraft/settings', desc: 'GET /api/boilercraft/settings' },
                { id: 'bc-faqs', name: 'FAQs API', endpoint: '/api/boilercraft/faqs', desc: 'GET /api/boilercraft/faqs' },
                { id: 'bc-verified', name: 'Verified Players API', endpoint: '/api/boilercraft/verified-players', desc: 'GET /api/boilercraft/verified-players' },
                { id: 'bc-watch-logs', name: 'BoilerWatch Logs', endpoint: '/api/boilercraft/boilerwatch/logs', desc: 'GET /api/boilercraft/boilerwatch/logs' },
                { id: 'bc-watch-stats', name: 'BoilerWatch Stats', endpoint: '/api/boilercraft/boilerwatch/stats', desc: 'GET /api/boilercraft/boilerwatch/stats' },
                { id: 'bc-members', name: 'Members API', endpoint: '/api/boilercraft/members', desc: 'GET /api/boilercraft/members' },
                { id: 'bc-mod-templates', name: 'Moderation Templates', endpoint: '/api/boilercraft/moderation/templates', desc: 'GET /api/boilercraft/moderation/templates' },
                { id: 'bc-analytics', name: 'Analytics API', endpoint: '/api/boilercraft/analytics', desc: 'GET /api/boilercraft/analytics' }
            ],
            arena: [
                { id: 'arena-page-live', name: 'Arena Live Feed', endpoint: '/arena/live', desc: 'GET /arena/live' },
                { id: 'arena-page-logs', name: 'Arena Logs Page', endpoint: '/arena/logs', desc: 'GET /arena/logs' },
                { id: 'arena-page-controls', name: 'Kiosk Manager Page', endpoint: '/arena/controls', desc: 'GET /arena/controls' },
                { id: 'arena-page-activity', name: 'Arena Activity Page', endpoint: '/arena/activity', desc: 'GET /arena/activity' },
                { id: 'arena-page-kiosk', name: 'Kiosk Picker', endpoint: '/arena/kiosk', desc: 'GET /arena/kiosk' },
                { id: 'arena-page-k1', name: 'Kiosk 1', endpoint: '/arena/kiosk/1', desc: 'GET /arena/kiosk/1' },
                { id: 'arena-page-k2', name: 'Kiosk 2', endpoint: '/arena/kiosk/2', desc: 'GET /arena/kiosk/2' },
                { id: 'arena-stats', name: 'Arena Stats', endpoint: '/api/arena/stats', desc: 'GET /api/arena/stats' },
                { id: 'arena-active', name: 'Live Feed API', endpoint: '/api/arena/active', desc: 'GET /api/arena/active' },
                { id: 'arena-logs', name: 'Sign-in Logs API', endpoint: '/api/arena/logs', desc: 'GET /api/arena/logs' },
                { id: 'arena-analytics', name: 'Arena Analytics', endpoint: '/api/arena/analytics', desc: 'GET /api/arena/analytics' },
                { id: 'arena-config', name: 'Kiosk Config', endpoint: '/api/arena/config', desc: 'GET /api/arena/config' },
                { id: 'arena-alerts', name: 'Kiosk Alerts', endpoint: '/api/arena/alerts', desc: 'GET /api/arena/alerts' }
            ],
            external: [
                { id: 'ext-ggleap', name: 'GGLeap Status', endpoint: '/api/ggleap/status', desc: 'GET /api/ggleap/status' },
                { id: 'ext-ggleap-games', name: 'GGLeap Games', endpoint: '/api/ggleap/games', desc: 'GET /api/ggleap/games' }
            ],
            ui: [
                { id: 'ui-toast', name: 'Toast Notifications', desc: 'Check toast system', type: 'ui-toast' },
                { id: 'ui-modal', name: 'Modal System', desc: 'Check modal manager', type: 'ui-modal' },
                { id: 'ui-loading', name: 'Loading States', desc: 'Check loading manager', type: 'ui-loading' },
                { id: 'ui-fonts', name: 'Font Loading', desc: 'Check Inter font', type: 'ui-fonts' },
                { id: 'ui-icons', name: 'Icon Library', desc: 'Check FontAwesome', type: 'ui-icons' }
            ],
            performance: [
                { id: 'perf-dom', name: 'DOM Size', desc: 'Check DOM element count', type: 'perf-dom' },
                { id: 'perf-timing', name: 'Page Load Time', desc: 'Check page load metrics', type: 'perf-timing' },
                { id: 'perf-api-latency', name: 'API Latency', endpoint: '/health', desc: 'Average API response time', type: 'perf-latency' }
            ]
        };
        
        this.init();
    }
    
    init() {
        this.addStyles();
        this.createDiagnosticsPanel();
    }
    
    addStyles() {
        if (document.getElementById('diagnostics-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'diagnostics-styles';
        style.textContent = '#diagnostics-panel{position:fixed;top:0;left:0;width:100%;height:100%;background:#0a0a0f;z-index:99999;display:none;overflow:hidden;font-family:"Inter",-apple-system,BlinkMacSystemFont,sans-serif}#diagnostics-panel.active{display:block;animation:diagFadeIn .3s ease}@keyframes diagFadeIn{from{opacity:0}to{opacity:1}}.diag-container{height:100%;display:flex;flex-direction:column}.diag-header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:16px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #7c3aed}.diag-title{font-size:22px;font-weight:700;color:#fff;display:flex;align-items:center;gap:12px}.diag-title i{color:#7c3aed;font-size:26px}.diag-version{font-size:11px;background:rgba(124,58,237,.3);padding:2px 8px;border-radius:4px;color:#a78bfa}.diag-header-actions{display:flex;gap:10px}.diag-btn{padding:10px 20px;border:none;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:all .2s;font-family:inherit}.diag-btn-primary{background:linear-gradient(135deg,#7c3aed 0%,#6d28d9 100%);color:#fff;box-shadow:0 4px 15px rgba(124,58,237,.4)}.diag-btn-primary:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(124,58,237,.5)}.diag-btn-sm{padding:6px 12px;font-size:12px}.diag-btn-xs{padding:4px 8px;font-size:11px}.diag-btn-secondary{background:#10b981;color:#fff}.diag-btn-secondary:hover{background:#059669}.diag-btn-outline{background:transparent;color:#9ca3af;border:1px solid #374151}.diag-btn-outline:hover{background:#1f2937;color:#fff}.diag-body{flex:1;display:flex;overflow:hidden}.diag-sidebar{width:260px;background:#111118;border-right:1px solid #2d2d4a;padding:16px;overflow-y:auto}.diag-system-status{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);border-radius:12px;padding:16px;margin-bottom:20px;border:1px solid #2d2d4a}.diag-status-indicator{display:flex;align-items:center;gap:10px;font-size:14px;color:#9ca3af}.diag-status-indicator i{color:#6b7280;font-size:12px}.diag-status-indicator.online i{color:#10b981}.diag-status-indicator.offline i{color:#ef4444}.diag-status-indicator.checking i{color:#f59e0b;animation:diagPulse 1s infinite}@keyframes diagPulse{0%,100%{opacity:1}50%{opacity:.5}}.diag-uptime{font-size:24px;font-weight:700;color:#fff;margin-top:8px;font-family:Consolas,monospace}.diag-nav-section{margin-bottom:24px}.diag-nav-title{font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;padding:0 8px}.diag-nav-btn{display:flex;align-items:center;gap:10px;width:100%;padding:10px 12px;background:transparent;border:none;border-radius:6px;color:#9ca3af;font-size:13px;cursor:pointer;transition:all .2s;text-decoration:none;font-family:inherit;text-align:left}.diag-nav-btn:hover{background:#1f1f2e;color:#fff}.diag-nav-btn i{width:18px;text-align:center;color:#7c3aed}.diag-content{flex:1;overflow-y:auto;padding:20px;background:#0d0d12}.diag-master-status{background:linear-gradient(135deg,#151520 0%,#1a1a28 100%);border-radius:16px;padding:24px;margin-bottom:24px;border:1px solid #2d2d4a}.diag-master-stats{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}.diag-stat-box{flex:1;min-width:140px;background:#0d0d12;border-radius:12px;padding:16px;display:flex;align-items:center;gap:12px;border:1px solid #2d2d4a}.diag-stat-icon{width:48px;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;background:rgba(124,58,237,.2);color:#a78bfa}.diag-stat-pass .diag-stat-icon{background:rgba(16,185,129,.2);color:#10b981}.diag-stat-fail .diag-stat-icon{background:rgba(239,68,68,.2);color:#ef4444}.diag-stat-warn .diag-stat-icon{background:rgba(245,158,11,.2);color:#f59e0b}.diag-stat-value{display:block;font-size:24px;font-weight:700;color:#fff}.diag-stat-label{font-size:12px;color:#6b7280}.diag-progress-container{height:6px;background:#1f1f2e;border-radius:3px;overflow:hidden;margin-bottom:16px}.diag-progress-bar{height:100%;width:0%;background:linear-gradient(90deg,#7c3aed 0%,#10b981 100%);border-radius:3px;transition:width .3s ease}.diag-overall-status{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:500;color:#9ca3af}.diag-overall-status i{font-size:12px}.diag-overall-status.pass{color:#10b981}.diag-overall-status.fail{color:#ef4444}.diag-overall-status.running{color:#f59e0b}.diag-section{background:#151520;border-radius:12px;margin-bottom:16px;border:1px solid #2d2d4a;overflow:hidden}.diag-section-header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:#1a1a28;border-bottom:1px solid #2d2d4a}.diag-section-header h3{font-size:15px;font-weight:600;color:#fff;display:flex;align-items:center;gap:10px;margin:0}.diag-section-header h3 i{color:#7c3aed}.diag-log-actions{display:flex;gap:8px}.diag-tests{padding:12px}.diag-test{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-radius:8px;margin:4px 0;background:#0d0d12;transition:all .2s;border-left:3px solid transparent}.diag-test:hover{background:#1a1a25}.diag-test.pass{border-left-color:#10b981}.diag-test.fail{border-left-color:#ef4444}.diag-test.warn{border-left-color:#f59e0b}.diag-test.running{border-left-color:#60a5fa}.diag-test-info{flex:1}.diag-test-name{display:block;font-size:14px;font-weight:500;color:#fff;margin-bottom:2px}.diag-test-desc{font-size:12px;color:#6b7280;font-family:Consolas,monospace}.diag-test-meta{font-size:11px;color:#4b5563;margin-top:4px}.diag-test-status{font-size:13px;font-weight:500;display:flex;align-items:center;gap:6px;min-width:120px;justify-content:flex-end}.diag-test-status i{font-size:14px}.diag-test-status.pending{color:#6b7280}.diag-test-status.running{color:#60a5fa}.diag-test-status.pass{color:#10b981}.diag-test-status.fail{color:#ef4444}.diag-test-status.warn{color:#f59e0b}.diag-test-status.skip{color:#6b7280}.diag-log{background:#0a0a0f;border-radius:8px;padding:12px;max-height:400px;overflow-y:auto;font-family:Consolas,Monaco,monospace;font-size:12px}.diag-log-entry{padding:4px 0;display:flex;gap:12px;border-bottom:1px solid #1a1a25}.diag-log-entry:last-child{border-bottom:none}.diag-log-time{color:#4b5563;min-width:90px;font-size:11px}.diag-log-level{min-width:60px;font-weight:600;font-size:11px}.diag-log-level.info{color:#60a5fa}.diag-log-level.success{color:#10b981}.diag-log-level.error{color:#ef4444}.diag-log-level.warn{color:#f59e0b}.diag-log-level.debug{color:#8b5cf6}.diag-log-msg{color:#9ca3af;flex:1}@keyframes diagSpin{to{transform:rotate(360deg)}}.diag-test-status.running i{animation:diagSpin 1s linear infinite}.diag-empty{text-align:center;padding:40px;color:#6b7280}.diag-empty i{font-size:48px;margin-bottom:16px;color:#374151}';
        document.head.appendChild(style);
        this.addEnhancedStyles();
    }

    addEnhancedStyles() {
        if (document.getElementById('diagnostics-styles-2')) return;
        var s2 = document.createElement('style');
        s2.id = 'diagnostics-styles-2';
        s2.textContent = [
            '#diagnostics-panel{background:radial-gradient(1200px 600px at 15% -10%,#141428 0,#0a0a0f 60%)!important}',
            '.diag-header{background:linear-gradient(135deg,#171735 0%,#0f1730 100%)!important;border-bottom:1px solid rgba(124,58,237,.55)!important;box-shadow:0 6px 30px rgba(0,0,0,.35)}',
            '.diag-title i{filter:drop-shadow(0 0 10px rgba(124,58,237,.7))}',
            '.diag-btn{border-radius:10px!important;letter-spacing:.2px}',
            '.diag-btn-danger{background:linear-gradient(135deg,#ef4444 0%,#b91c1c 100%);color:#fff;box-shadow:0 4px 15px rgba(239,68,68,.35)}',
            '.diag-btn-danger:hover{transform:translateY(-2px)}',
            '.diag-btn:disabled{opacity:.45;cursor:not-allowed;transform:none!important;box-shadow:none!important}',
            '.diag-sidebar{background:linear-gradient(180deg,#0e0e18 0%,#0b0b13 100%)!important;width:280px!important}',
            '.diag-nav-btn{border-radius:9px;transition:background .15s,transform .15s;display:flex;align-items:center;gap:10px}',
            '.diag-nav-btn:hover{background:rgba(124,58,237,.16)!important;transform:translateX(3px)}',
            '.diag-nav-count{margin-left:auto;font-size:10px;font-weight:700;padding:2px 7px;border-radius:20px;background:rgba(255,255,255,.06);color:#9ca3af;min-width:16px;text-align:center}',
            '.diag-nav-count.has-fail{background:rgba(239,68,68,.2);color:#fca5a5}',
            '.diag-nav-count.has-warn{background:rgba(245,158,11,.2);color:#fcd34d}',
            '.diag-nav-count.all-pass{background:rgba(16,185,129,.2);color:#6ee7b7}',
            '.diag-master-status{background:linear-gradient(135deg,#15152b 0%,#101a34 100%)!important;border:1px solid rgba(124,58,237,.28)!important;border-radius:16px!important;box-shadow:0 10px 40px rgba(0,0,0,.3)}',
            '.diag-stat-box{background:rgba(255,255,255,.03)!important;border:1px solid rgba(255,255,255,.06)!important;border-radius:12px!important;transition:transform .15s}',
            '.diag-stat-box:hover{transform:translateY(-2px)}',
            '.diag-stat-pass .diag-stat-value{color:#34d399}','.diag-stat-fail .diag-stat-value{color:#f87171}','.diag-stat-warn .diag-stat-value{color:#fbbf24}',
            '.diag-progress-container{height:10px!important;background:rgba(255,255,255,.06)!important;border-radius:20px!important;overflow:hidden}',
            '.diag-progress-bar{background:linear-gradient(90deg,#7c3aed,#22d3ee)!important;box-shadow:0 0 18px rgba(124,58,237,.6);transition:width .4s ease}',
            '.diag-run-meta{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:12.5px;color:#9ca3af;font-variant-numeric:tabular-nums}',
            '.diag-run-meta span{display:inline-flex;align-items:center;gap:6px}',
            '.diag-run-meta i{color:#7c3aed}',
            '.diag-overall-status{font-weight:600}',
            '.diag-section{background:linear-gradient(180deg,#101019 0%,#0d0d15 100%)!important;border:1px solid rgba(255,255,255,.06)!important;border-radius:14px!important;margin-bottom:16px!important;overflow:hidden}',
            '.diag-section.cat-active{border-color:rgba(124,58,237,.55)!important;box-shadow:0 0 0 1px rgba(124,58,237,.25),0 8px 30px rgba(124,58,237,.12)}',
            '.diag-section-header{position:sticky;top:0;z-index:2;background:linear-gradient(180deg,#161628,#12121e)!important;backdrop-filter:blur(6px);border-bottom:1px solid rgba(255,255,255,.06)!important;padding:14px 16px!important}',
            '.diag-section-header h3{font-size:15px!important;display:flex;align-items:center;gap:10px}',
            '.diag-section-header h3 i{color:#a78bfa}',
            '.diag-section-tools{display:flex;align-items:center;gap:12px}',
            '.diag-section-summary{font-size:11.5px;color:#9ca3af;font-weight:600;font-variant-numeric:tabular-nums}',
            '.diag-test{border-radius:10px!important;border:1px solid rgba(255,255,255,.05)!important;margin:8px 12px!important;padding:11px 14px!important;transition:background .15s,border-color .15s}',
            '.diag-test:hover{background:rgba(255,255,255,.03)!important}',
            '.diag-test.pass{border-left:3px solid #10b981!important}',
            '.diag-test.fail{border-left:3px solid #ef4444!important;background:rgba(239,68,68,.05)!important}',
            '.diag-test.warn{border-left:3px solid #f59e0b!important}',
            '.diag-test.running{border-left:3px solid #7c3aed!important;background:rgba(124,58,237,.06)!important}',
            '.diag-test-name{font-weight:600!important}',
            '.diag-test-desc{color:#6b7280!important;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px!important}',
            '.diag-test-meta{display:block;margin-top:3px;color:#8b5cf6!important;font-size:10.5px!important;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}',
            '.diag-test-status{border-radius:20px!important;padding:5px 12px!important;font-size:11.5px!important;font-weight:700!important;white-space:nowrap}',
            '.diag-test-status.pass{background:rgba(16,185,129,.15)!important;color:#34d399!important}',
            '.diag-test-status.fail{background:rgba(239,68,68,.15)!important;color:#f87171!important}',
            '.diag-test-status.warn{background:rgba(245,158,11,.15)!important;color:#fbbf24!important}',
            '.diag-test-status.running{background:rgba(124,58,237,.18)!important;color:#c4b5fd!important}',
            '.diag-test-status.pending{background:rgba(255,255,255,.05)!important;color:#6b7280!important}',
            '.diag-test-status.skip{background:rgba(148,163,184,.12)!important;color:#94a3b8!important}',
            '.diag-status-indicator.online{color:#34d399}','.diag-status-indicator.offline{color:#f87171}','.diag-status-indicator.checking{color:#c4b5fd}',
            '.diag-log{background:#07070c!important;border-radius:10px!important;border:1px solid rgba(255,255,255,.06)!important}',
            '.diag-content::-webkit-scrollbar,.diag-sidebar::-webkit-scrollbar,.diag-log::-webkit-scrollbar{width:10px}',
            '.diag-content::-webkit-scrollbar-thumb,.diag-sidebar::-webkit-scrollbar-thumb,.diag-log::-webkit-scrollbar-thumb{background:rgba(124,58,237,.4);border-radius:20px}',
            '.diag-uptime{font-variant-numeric:tabular-nums;font-size:20px;font-weight:700;color:#e5e7eb}'
        ].join('');
        document.head.appendChild(s2);
    }
    
    createDiagnosticsPanel() {
        const panel = document.createElement('div');
        panel.id = 'diagnostics-panel';
        panel.innerHTML = this.getPanelHTML();
        document.body.appendChild(panel);
        this.initializeTestContainers();
    }
    
    getPanelHTML() {
        return '<div class="diag-container">' +
            '<div class="diag-header">' +
                '<div class="diag-title"><i class="fas fa-terminal"></i> Master Diagnostics Console <span class="diag-version">v2.0</span></div>' +
                '<div class="diag-header-actions">' +
                    '<button class="diag-btn diag-btn-primary" id="diag-full-btn" onclick="window.diagnostics.runFullDiagnostics()"><i class="fas fa-rocket"></i> Full Deep Scan</button>' +
                    '<button class="diag-btn diag-btn-secondary" id="diag-quick-btn" onclick="window.diagnostics.runQuickCheck()"><i class="fas fa-bolt"></i> Quick Check</button>' +
                    '<button class="diag-btn diag-btn-danger" id="diag-stop-btn" style="display:none;" onclick="window.diagnostics.requestStop()"><i class="fas fa-stop"></i> Stop</button>' +
                    '<button class="diag-btn diag-btn-outline" onclick="window.diagnostics.closeDiagnostics()"><i class="fas fa-times"></i> Close</button>' +
                '</div>' +
            '</div>' +
            '<div class="diag-body">' +
                '<div class="diag-sidebar">' +
                    '<div class="diag-system-status">' +
                        '<div class="diag-status-indicator" id="system-health-indicator"><i class="fas fa-circle"></i><span>System Status</span></div>' +
                        '<div class="diag-uptime" id="diag-uptime">--:--:--</div>' +
                    '</div>' +
                    '<div class="diag-nav-section">' +
                        '<div class="diag-nav-title">Quick Actions</div>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.runFullDiagnostics()"><i class="fas fa-rocket"></i> Full Diagnostics</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.runQuickCheck()"><i class="fas fa-bolt"></i> Quick Check</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.clearResults()"><i class="fas fa-eraser"></i> Clear Results</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.exportResults()"><i class="fas fa-file-download"></i> Export Report</button>' +
                    '</div>' +
                    '<div class="diag-nav-section">' +
                        '<div class="diag-nav-title">Test Categories</div>' +
                        this.categoryMeta.map(function(c){ return '<button class="diag-nav-btn" id="nav-' + c.id + '" onclick="window.diagnostics.scrollTo(\'' + c.id + '\')"><i class="fas ' + c.icon + '"></i> ' + c.title + ' <span class="diag-nav-count" id="navcount-' + c.id + '"></span></button>'; }).join('') +
                    '</div>' +
                    '<div class="diag-nav-section">' +
                        '<div class="diag-nav-title">Navigation</div>' +
                        '<a href="/login" class="diag-nav-btn"><i class="fas fa-sign-in-alt"></i> Go to Login</a>' +
                        '<a href="/dashboard" class="diag-nav-btn"><i class="fas fa-home"></i> Go to Dashboard</a>' +
                        '<a href="/settings" class="diag-nav-btn"><i class="fas fa-cog"></i> Bot Settings</a>' +
                    '</div>' +
                '</div>' +
                '<div class="diag-content">' +
                    '<div class="diag-master-status" id="diag-master-status">' +
                        '<div class="diag-master-stats">' +
                            '<div class="diag-stat-box"><div class="diag-stat-icon"><i class="fas fa-vial"></i></div><div class="diag-stat-info"><span class="diag-stat-value" id="diag-total">0</span><span class="diag-stat-label">Total Tests</span></div></div>' +
                            '<div class="diag-stat-box diag-stat-pass"><div class="diag-stat-icon"><i class="fas fa-check-circle"></i></div><div class="diag-stat-info"><span class="diag-stat-value" id="diag-passed">0</span><span class="diag-stat-label">Passed</span></div></div>' +
                            '<div class="diag-stat-box diag-stat-fail"><div class="diag-stat-icon"><i class="fas fa-times-circle"></i></div><div class="diag-stat-info"><span class="diag-stat-value" id="diag-failed">0</span><span class="diag-stat-label">Failed</span></div></div>' +
                            '<div class="diag-stat-box diag-stat-warn"><div class="diag-stat-icon"><i class="fas fa-exclamation-triangle"></i></div><div class="diag-stat-info"><span class="diag-stat-value" id="diag-warnings">0</span><span class="diag-stat-label">Warnings</span></div></div>' +
                            '<div class="diag-stat-box"><div class="diag-stat-icon"><i class="fas fa-stopwatch"></i></div><div class="diag-stat-info"><span class="diag-stat-value" id="diag-duration">0ms</span><span class="diag-stat-label">Duration</span></div></div>' +
                        '</div>' +
                        '<div class="diag-progress-container"><div class="diag-progress-bar" id="diag-progress-bar"></div></div>' +
                        '<div class="diag-overall-status" id="diag-overall"><i class="fas fa-circle"></i> Ready to run diagnostics</div>' +
                        '<div class="diag-run-meta">' +
                            '<span id="diag-elapsed"><i class="fas fa-stopwatch"></i> 00:00</span>' +
                            '<span id="diag-eta"><i class="fas fa-hourglass-half"></i> ETA --:--</span>' +
                            '<span id="diag-progress-text">0 / 0 tests</span>' +
                        '</div>' +
                    '</div>' +
                    this.getSectionsHTML() +
                    '<div class="diag-section" id="diag-log">' +
                        '<div class="diag-section-header"><h3><i class="fas fa-terminal"></i> Diagnostic Log</h3>' +
                        '<div class="diag-log-actions"><button class="diag-btn diag-btn-xs" onclick="window.diagnostics.toggleLogVerbosity()"><i class="fas fa-filter"></i> Toggle Verbose</button>' +
                        '<button class="diag-btn diag-btn-xs" onclick="document.getElementById(\'diag-log-content\').innerHTML = \'\'"><i class="fas fa-trash"></i> Clear</button></div></div>' +
                        '<div class="diag-log" id="diag-log-content"></div>' +
                    '</div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }
    
    getSectionsHTML() {
        return this.categoryMeta.map(function(s) {
            return '<div class="diag-section" id="diag-' + s.id + '">' +
                '<div class="diag-section-header"><h3><i class="fas ' + s.icon + '"></i> ' + s.title + '</h3>' +
                '<div class="diag-section-tools"><span class="diag-section-summary" id="summary-' + s.id + '"></span>' +
                '<button class="diag-btn diag-btn-sm" onclick="window.diagnostics.runCategoryTests(\'' + s.id + '\')"><i class="fas fa-play"></i> Run</button></div></div>' +
                '<div class="diag-tests" id="tests-' + s.id + '"></div>' +
            '</div>';
        }).join('');
    }
    
    initializeTestContainers() {
        for (const category in this.testDefinitions) {
            const tests = this.testDefinitions[category];
            const container = document.getElementById('tests-' + category);
            if (container) {
                if (tests.length === 0) {
                    container.innerHTML = '<div class="diag-empty"><i class="fas fa-inbox"></i><p>No tests in this category</p></div>';
                } else {
                    container.innerHTML = tests.map(test => 
                        '<div class="diag-test" id="test-row-' + test.id + '" data-test="' + test.id + '">' +
                            '<div class="diag-test-info">' +
                                '<span class="diag-test-name">' + test.name + '</span>' +
                                '<span class="diag-test-desc">' + test.desc + '</span>' +
                                '<span class="diag-test-meta" id="meta-' + test.id + '"></span>' +
                            '</div>' +
                            '<div class="diag-test-status pending" id="status-' + test.id + '">' +
                                '<i class="fas fa-circle"></i> Pending' +
                            '</div>' +
                        '</div>'
                    ).join('');
                }
            }
        }
        
        this.log('info', 'Master Diagnostics Console initialized');
        var totalTests = 0;
        for (var cat in this.testDefinitions) {
            totalTests += this.testDefinitions[cat].length;
        }
        this.log('info', totalTests + ' tests available');
    }
    
    openDiagnostics() {
        var panel = document.getElementById('diagnostics-panel');
        if (panel) {
            panel.classList.add('active');
            this.isOpen = true;
            this.startTime = Date.now();
            this.updateUptime();
            this.log('info', '═══════════════════════════════════════');
            this.log('info', 'Master Diagnostics Console opened');
            this.log('info', 'Timestamp: ' + new Date().toISOString());
            this.log('info', '═══════════════════════════════════════');
        }
    }
    
    closeDiagnostics() {
        var panel = document.getElementById('diagnostics-panel');
        if (panel) {
            panel.classList.remove('active');
            this.isOpen = false;
        }
    }
    
    scrollTo(sectionId) {
        var section = document.getElementById('diag-' + sectionId);
        if (section) {
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
    
    updateUptime() {
        var self = this;
        var uptimeEl = document.getElementById('diag-uptime');
        if (uptimeEl && this.startTime) {
            var elapsed = Date.now() - this.startTime;
            var hours = Math.floor(elapsed / 3600000);
            var minutes = Math.floor((elapsed % 3600000) / 60000);
            var seconds = Math.floor((elapsed % 60000) / 1000);
            uptimeEl.textContent = 
                (hours < 10 ? '0' : '') + hours + ':' + 
                (minutes < 10 ? '0' : '') + minutes + ':' + 
                (seconds < 10 ? '0' : '') + seconds;
        }
        if (this.isOpen) {
            setTimeout(function() { self.updateUptime(); }, 1000);
        }
    }
    
    log(type, message) {
        var logContainer = document.getElementById('diag-log-content');
        if (!logContainer) return;
        
        var entry = document.createElement('div');
        entry.className = 'diag-log-entry';
        entry.innerHTML = '<span class="diag-log-time">' + new Date().toLocaleTimeString() + '</span>' +
            '<span class="diag-log-level ' + type + '">' + type.toUpperCase() + '</span>' +
            '<span class="diag-log-msg">' + message + '</span>';
        logContainer.appendChild(entry);
        logContainer.scrollTop = logContainer.scrollHeight;
    }
    
    updateTestStatus(testId, status, message, duration) {
        var statusEl = document.getElementById('status-' + testId);
        var rowEl = document.getElementById('test-row-' + testId);
        var metaEl = document.getElementById('meta-' + testId);
        
        if (!statusEl) return;
        
        var icons = {
            pending: 'fa-circle',
            running: 'fa-spinner fa-spin',
            pass: 'fa-check-circle',
            fail: 'fa-times-circle',
            warn: 'fa-exclamation-circle',
            skip: 'fa-forward'
        };
        
        var labels = {
            pending: 'Pending',
            running: 'Testing...',
            pass: 'Passed',
            fail: 'Failed',
            warn: 'Warning',
            skip: 'Skipped'
        };
        
        statusEl.className = 'diag-test-status ' + status;
        statusEl.innerHTML = '<i class="fas ' + icons[status] + '"></i> ' + (message || labels[status]);
        
        if (rowEl) {
            rowEl.className = 'diag-test ' + status;
        }
        
        if (metaEl && duration) {
            metaEl.textContent = 'Response time: ' + duration + 'ms';
        }
    }
    
    updateStats() {
        var tests = [];
        for (var key in this.testResults) {
            tests.push(this.testResults[key]);
        }
        var total = tests.length;
        var passed = tests.filter(function(t) { return t === 'pass'; }).length;
        var failed = tests.filter(function(t) { return t === 'fail'; }).length;
        var warnings = tests.filter(function(t) { return t === 'warn'; }).length;
        
        document.getElementById('diag-total').textContent = total;
        document.getElementById('diag-passed').textContent = passed;
        document.getElementById('diag-failed').textContent = failed;
        document.getElementById('diag-warnings').textContent = warnings;
        
        var allTests = 0;
        for (var cat in this.testDefinitions) {
            allTests += this.testDefinitions[cat].length;
        }
        var progress = (total / allTests) * 100;
        document.getElementById('diag-progress-bar').style.width = progress + '%';
        
        var overallEl = document.getElementById('diag-overall');
        var indicatorEl = document.getElementById('system-health-indicator');
        
        if (total === 0) {
            overallEl.className = 'diag-overall-status';
            overallEl.innerHTML = '<i class="fas fa-circle"></i> Ready to run diagnostics';
        } else if (failed > 0) {
            overallEl.className = 'diag-overall-status fail';
            overallEl.innerHTML = '<i class="fas fa-times-circle"></i> ' + failed + ' issue(s) detected - Review failed tests';
            indicatorEl.className = 'diag-status-indicator offline';
        } else if (warnings > 0) {
            overallEl.className = 'diag-overall-status warn';
            overallEl.innerHTML = '<i class="fas fa-exclamation-circle"></i> All tests passed with ' + warnings + ' warning(s)';
            indicatorEl.className = 'diag-status-indicator online';
        } else {
            overallEl.className = 'diag-overall-status pass';
            overallEl.innerHTML = '<i class="fas fa-check-circle"></i> All systems operational';
            indicatorEl.className = 'diag-status-indicator online';
        }
        
        if (this.startTime) {
            document.getElementById('diag-duration').textContent = (Date.now() - this.startTime) + 'ms';
        }
    }
    
    async runTest(test) {
        var self = this;
        this.updateTestStatus(test.id, 'running');
        
        if (test.type) {
            return await this.runSpecialTest(test);
        }
        
        try {
            var samples = (this.deepMode && this.running) ? this.samples : 1;
            var durs = [];
            var response = null;
            for (var s = 0; s < samples; s++) {
                var startTime = performance.now();
                response = await this.fetchWithTimeout(test.endpoint, this.reqTimeoutMs);
                durs.push(performance.now() - startTime);
                if (s < samples - 1) await this.sleep(120);
            }
            var dsum = 0; for (var di = 0; di < durs.length; di++) dsum += durs[di];
            var duration = Math.round(dsum / durs.length);
            
            if (response.ok) {
                this.testResults[test.id] = 'pass';
                this.updateTestStatus(test.id, 'pass', response.status + ' OK', duration);
                this.log('success', '✓ ' + test.name + ' - ' + response.status + ' (' + duration + 'ms)');
            } else if (response.status === 401 || response.status === 403) {
                this.testResults[test.id] = 'warn';
                this.updateTestStatus(test.id, 'warn', 'Auth Required', duration);
                this.log('warn', '⚠ ' + test.name + ' - Requires authentication');
            } else {
                this.testResults[test.id] = 'fail';
                this.updateTestStatus(test.id, 'fail', 'HTTP ' + response.status, duration);
                this.log('error', '✗ ' + test.name + ' - HTTP ' + response.status);
            }
        } catch (error) {
            var msg = (error && error.name === 'AbortError') ? 'Timeout' : 'Network Error';
            this.testResults[test.id] = 'fail';
            this.updateTestStatus(test.id, 'fail', msg);
            this.log('error', '✗ ' + test.name + ' - ' + (error && error.message ? error.message : msg));
        }
        
        this.updateStats();
    }
    
    async runSpecialTest(test) {
        switch (test.type) {
            case 'ping':
                return await this.runPingTest(test);
            case 'session':
                return await this.runSessionTest(test);
            case 'browser-memory':
                return this.runMemoryTest(test);
            case 'storage':
                return this.runStorageTest(test);
            case 'ui-toast':
            case 'ui-modal':
            case 'ui-loading':
            case 'ui-fonts':
            case 'ui-icons':
                return this.runUITest(test);
            case 'perf-dom':
            case 'perf-timing':
            case 'perf-latency':
                return await this.runPerfTest(test);
            default:
                this.updateTestStatus(test.id, 'skip', 'Unknown type');
        }
    }
    
    async runPingTest(test) {
        var times = [];
        for (var i = 0; i < 3; i++) {
            var start = performance.now();
            await fetch('/health');
            times.push(performance.now() - start);
        }
        var sum = 0;
        for (var j = 0; j < times.length; j++) sum += times[j];
        var avg = Math.round(sum / times.length);
        
        if (avg < 100) {
            this.testResults[test.id] = 'pass';
            this.updateTestStatus(test.id, 'pass', avg + 'ms avg');
            this.log('success', '✓ Server Ping - ' + avg + 'ms average (excellent)');
        } else if (avg < 300) {
            this.testResults[test.id] = 'warn';
            this.updateTestStatus(test.id, 'warn', avg + 'ms avg');
            this.log('warn', '⚠ Server Ping - ' + avg + 'ms average (acceptable)');
        } else {
            this.testResults[test.id] = 'fail';
            this.updateTestStatus(test.id, 'fail', avg + 'ms avg');
            this.log('error', '✗ Server Ping - ' + avg + 'ms average (slow)');
        }
        this.updateStats();
    }
    
    async runSessionTest(test) {
        try {
            var response = await fetch('/api/auth/user');
            var data = await response.json();
            
            if (data.authenticated) {
                this.testResults[test.id] = 'pass';
                var user = (data.user && data.user.username) || (data.user && data.user.global_name) || 'Admin';
                this.updateTestStatus(test.id, 'pass', 'Logged in as ' + user);
                this.log('success', '✓ Session active - User: ' + user);
            } else {
                this.testResults[test.id] = 'warn';
                this.updateTestStatus(test.id, 'warn', 'Not authenticated');
                this.log('warn', '⚠ No active session - Some tests may fail');
            }
        } catch (e) {
            this.testResults[test.id] = 'fail';
            this.updateTestStatus(test.id, 'fail', 'Check failed');
            this.log('error', '✗ Session check failed: ' + e.message);
        }
        this.updateStats();
    }
    
    runMemoryTest(test) {
        if (performance.memory) {
            var used = Math.round(performance.memory.usedJSHeapSize / 1048576);
            var total = Math.round(performance.memory.jsHeapSizeLimit / 1048576);
            var percent = Math.round((used / total) * 100);
            
            if (percent < 50) {
                this.testResults[test.id] = 'pass';
                this.updateTestStatus(test.id, 'pass', used + 'MB / ' + total + 'MB');
                this.log('success', '✓ Memory usage: ' + percent + '% (' + used + 'MB)');
            } else if (percent < 80) {
                this.testResults[test.id] = 'warn';
                this.updateTestStatus(test.id, 'warn', used + 'MB / ' + total + 'MB');
                this.log('warn', '⚠ Memory usage: ' + percent + '% (' + used + 'MB)');
            } else {
                this.testResults[test.id] = 'fail';
                this.updateTestStatus(test.id, 'fail', used + 'MB / ' + total + 'MB');
                this.log('error', '✗ High memory usage: ' + percent + '% (' + used + 'MB)');
            }
        } else {
            this.testResults[test.id] = 'skip';
            this.updateTestStatus(test.id, 'skip', 'Not available');
            this.log('info', 'Memory API not available in this browser');
        }
        this.updateStats();
    }
    
    runStorageTest(test) {
        try {
            localStorage.setItem('diag_test', 'test');
            localStorage.removeItem('diag_test');
            this.testResults[test.id] = 'pass';
            this.updateTestStatus(test.id, 'pass', 'Available');
            this.log('success', '✓ Local storage is available');
        } catch (e) {
            this.testResults[test.id] = 'fail';
            this.updateTestStatus(test.id, 'fail', 'Blocked');
            this.log('error', '✗ Local storage is blocked or full');
        }
        this.updateStats();
    }
    
    runUITest(test) {
        switch (test.type) {
            case 'ui-toast':
                if ((window.LionByte && window.LionByte.toast) || typeof showToast === 'function') {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', 'Available');
                    this.log('success', '✓ Toast notification system available');
                } else {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', 'Not found');
                    this.log('warn', '⚠ Toast system not detected');
                }
                break;
            case 'ui-modal':
                if ((window.LionByte && window.LionByte.ModalManager) || document.querySelector('.modal-overlay')) {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', 'Available');
                    this.log('success', '✓ Modal system available');
                } else {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', 'Not found');
                    this.log('warn', '⚠ Modal system not detected');
                }
                break;
            case 'ui-loading':
                if (window.LionByte && window.LionByte.LoadingState) {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', 'Available');
                    this.log('success', '✓ Loading state manager available');
                } else {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', 'Not found');
                    this.log('warn', '⚠ Loading state manager not detected');
                }
                break;
            case 'ui-fonts':
                if (document.fonts && document.fonts.check('16px Inter')) {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', 'Loaded');
                    this.log('success', '✓ Inter font loaded');
                } else {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', 'Loading...');
                    this.log('warn', '⚠ Inter font may still be loading');
                }
                break;
            case 'ui-icons':
                var iconTest = document.querySelector('.fas, .fab, .far');
                if (iconTest) {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', 'Loaded');
                    this.log('success', '✓ FontAwesome icons loaded');
                } else {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', 'Loading...');
                    this.log('warn', '⚠ FontAwesome may still be loading');
                }
                break;
        }
        this.updateStats();
    }
    
    async runPerfTest(test) {
        switch (test.type) {
            case 'perf-dom':
                var elements = document.querySelectorAll('*').length;
                if (elements < 1500) {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', elements + ' elements');
                    this.log('success', '✓ DOM size: ' + elements + ' elements (optimal)');
                } else if (elements < 3000) {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', elements + ' elements');
                    this.log('warn', '⚠ DOM size: ' + elements + ' elements (moderate)');
                } else {
                    this.testResults[test.id] = 'fail';
                    this.updateTestStatus(test.id, 'fail', elements + ' elements');
                    this.log('error', '✗ DOM size: ' + elements + ' elements (large)');
                }
                break;
            case 'perf-timing':
                if (performance.timing) {
                    var loadTime = performance.timing.loadEventEnd - performance.timing.navigationStart;
                    if (loadTime < 2000) {
                        this.testResults[test.id] = 'pass';
                        this.updateTestStatus(test.id, 'pass', loadTime + 'ms');
                        this.log('success', '✓ Page load time: ' + loadTime + 'ms (fast)');
                    } else if (loadTime < 5000) {
                        this.testResults[test.id] = 'warn';
                        this.updateTestStatus(test.id, 'warn', loadTime + 'ms');
                        this.log('warn', '⚠ Page load time: ' + loadTime + 'ms (acceptable)');
                    } else {
                        this.testResults[test.id] = 'fail';
                        this.updateTestStatus(test.id, 'fail', loadTime + 'ms');
                        this.log('error', '✗ Page load time: ' + loadTime + 'ms (slow)');
                    }
                } else {
                    this.testResults[test.id] = 'skip';
                    this.updateTestStatus(test.id, 'skip', 'N/A');
                }
                break;
            case 'perf-latency':
                var times = [];
                for (var i = 0; i < 5; i++) {
                    var start = performance.now();
                    await fetch('/health');
                    times.push(performance.now() - start);
                    await new Promise(function(r) { setTimeout(r, 100); });
                }
                var sum = 0;
                for (var j = 0; j < times.length; j++) sum += times[j];
                var avg = Math.round(sum / times.length);
                if (avg < 50) {
                    this.testResults[test.id] = 'pass';
                    this.updateTestStatus(test.id, 'pass', avg + 'ms avg');
                    this.log('success', '✓ API latency: ' + avg + 'ms average');
                } else if (avg < 150) {
                    this.testResults[test.id] = 'warn';
                    this.updateTestStatus(test.id, 'warn', avg + 'ms avg');
                    this.log('warn', '⚠ API latency: ' + avg + 'ms average');
                } else {
                    this.testResults[test.id] = 'fail';
                    this.updateTestStatus(test.id, 'fail', avg + 'ms avg');
                    this.log('error', '✗ API latency: ' + avg + 'ms average');
                }
                break;
        }
        this.updateStats();
    }
    
    async runCategoryTests(category) {
        var tests = this.testDefinitions[category] || [];
        this.log('info', '▶ ' + this.categoryTitle(category) + ' — ' + tests.length + ' checks');
        this.highlightCategory(category, true);
        for (var i = 0; i < tests.length; i++) {
            if (this.cancelRequested) break;
            var t0 = performance.now();
            await this.runTest(tests[i]);
            this.completedCount++;
            this.updateEta();
            this.updateCategoryBadge(category);
            if (this.deepMode && this.running && !this.cancelRequested) {
                var wait = this.cadenceMs - (performance.now() - t0);
                if (wait > 0) await this.pacedWait(wait);
            } else {
                await this.sleep(40);
            }
        }
        this.highlightCategory(category, false);
        this.updateCategoryBadge(category);
    }
    
    async runQuickCheck() {
        if (this.running) return;
        this.running = true; this.cancelRequested = false; this.deepMode = false;
        this.testResults = {}; this.completedCount = 0; this.startTime = Date.now();
        this.setRunningUI(true);
        this.startElapsedTimer();
        this.log('info', '═══════════════════════════════════════');
        this.log('info', '⚡ QUICK SYSTEM CHECK');
        this.log('info', '═══════════════════════════════════════');
        var indicatorEl = document.getElementById('system-health-indicator');
        if (indicatorEl) indicatorEl.className = 'diag-status-indicator checking';
        var ids = ['sys-health','auth-session','bot-stats','api-members','arena-stats','shift-stats','music-status','bc-status'];
        var quick = [];
        for (var q = 0; q < ids.length; q++) { var qt = this.findTest(ids[q]); if (qt) quick.push(qt); }
        this.plannedTotal = quick.length; this.updateEta();
        for (var i = 0; i < quick.length && !this.cancelRequested; i++) {
            await this.runTest(quick[i]);
            this.completedCount++; this.updateEta();
            await this.sleep(120);
        }
        this.finishRun('Quick check');
    }
    
    async runFullDiagnostics() {
        if (this.running) return;
        this.running = true; this.cancelRequested = false; this.deepMode = true;
        this.testResults = {}; this.completedCount = 0; this.startTime = Date.now();
        this.plannedTotal = this.countAllTests();
        this.setRunningUI(true);
        this.startElapsedTimer();
        var mins = Math.round(this.plannedTotal * this.cadenceMs / 60000);
        this.log('info', '═══════════════════════════════════════════════════════');
        this.log('info', '🚀 FULL DEEP SCAN — ' + this.plannedTotal + ' checks (est. ~' + mins + ' min)');
        this.log('info', 'Started: ' + new Date().toLocaleString());
        this.log('info', '═══════════════════════════════════════════════════════');
        var indicatorEl = document.getElementById('system-health-indicator');
        if (indicatorEl) indicatorEl.className = 'diag-status-indicator checking';
        var overallEl = document.getElementById('diag-overall');
        if (overallEl) { overallEl.className = 'diag-overall-status running'; overallEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running full deep scan...'; }
        this.updateEta();
        var categories = this.categoryMeta.map(function(c){ return c.id; });
        for (var i = 0; i < categories.length && !this.cancelRequested; i++) {
            await this.runCategoryTests(categories[i]);
        }
        this.finishRun('Full deep scan');
    }
    
    countAllTests() {
        var n = 0;
        for (var c in this.testDefinitions) n += this.testDefinitions[c].length;
        return n;
    }
    
    findTest(id) {
        for (var c in this.testDefinitions) {
            var arr = this.testDefinitions[c];
            for (var i = 0; i < arr.length; i++) if (arr[i].id === id) return arr[i];
        }
        return null;
    }
    
    categoryTitle(id) {
        for (var i = 0; i < this.categoryMeta.length; i++) if (this.categoryMeta[i].id === id) return this.categoryMeta[i].title;
        return id;
    }
    
    sleep(ms) { return new Promise(function(r){ setTimeout(r, ms); }); }
    
    async pacedWait(ms) {
        var end = performance.now() + ms;
        while (performance.now() < end) {
            if (this.cancelRequested) return;
            await this.sleep(Math.min(200, Math.max(20, end - performance.now())));
        }
    }
    
    async fetchWithTimeout(url, ms) {
        var ctrl = new AbortController();
        var to = setTimeout(function(){ ctrl.abort(); }, ms || this.reqTimeoutMs);
        try { return await fetch(url, { signal: ctrl.signal, credentials: 'same-origin', headers: { 'X-Diagnostics': '1' } }); }
        finally { clearTimeout(to); }
    }
    
    requestStop() {
        if (!this.running) return;
        this.cancelRequested = true;
        this.log('warn', '■ Stop requested — finishing current check...');
        var b = document.getElementById('diag-stop-btn'); if (b) { b.disabled = true; b.innerHTML = '<i class="fas fa-hourglass-half"></i> Stopping'; }
    }
    
    setRunningUI(on) {
        var full = document.getElementById('diag-full-btn');
        var quick = document.getElementById('diag-quick-btn');
        var stop = document.getElementById('diag-stop-btn');
        if (full) full.disabled = on;
        if (quick) quick.disabled = on;
        if (stop) { stop.style.display = on ? 'inline-flex' : 'none'; if (on) { stop.disabled = false; stop.innerHTML = '<i class="fas fa-stop"></i> Stop'; } }
    }
    
    startElapsedTimer() {
        var self = this;
        if (this._elapsedTimer) clearInterval(this._elapsedTimer);
        this._elapsedTimer = setInterval(function(){ self.updateElapsed(); }, 1000);
    }
    
    updateElapsed() {
        if (!this.startTime) return;
        var el = document.getElementById('diag-elapsed');
        if (el) el.innerHTML = '<i class="fas fa-stopwatch"></i> ' + this.fmtClock(Date.now() - this.startTime);
        var dur = document.getElementById('diag-duration');
        if (dur) dur.textContent = Math.round((Date.now() - this.startTime) / 1000) + 's';
    }
    
    updateEta() {
        var remaining = Math.max(0, this.plannedTotal - this.completedCount);
        var perTest = this.deepMode ? this.cadenceMs : 250;
        var etaEl = document.getElementById('diag-eta');
        if (etaEl) etaEl.innerHTML = '<i class="fas fa-hourglass-half"></i> ETA ' + (this.running ? this.fmtClock(remaining * perTest) : '--:--');
        var pt = document.getElementById('diag-progress-text');
        if (pt) pt.textContent = this.completedCount + ' / ' + this.plannedTotal + ' tests';
        var bar = document.getElementById('diag-progress-bar');
        if (bar && this.plannedTotal) bar.style.width = Math.round(this.completedCount / this.plannedTotal * 100) + '%';
        this.updateElapsed();
    }
    
    fmtClock(ms) {
        var s = Math.max(0, Math.round(ms / 1000));
        var m = Math.floor(s / 60); s = s % 60;
        return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }
    
    highlightCategory(id, on) {
        var sec = document.getElementById('diag-' + id);
        if (sec) sec.classList.toggle('cat-active', !!on);
        var nav = document.getElementById('nav-' + id);
        if (nav) nav.classList.toggle('cat-active', !!on);
    }
    
    updateCategoryBadge(id) {
        var tests = this.testDefinitions[id] || [];
        var done = 0, fail = 0, warn = 0, pass = 0;
        for (var i = 0; i < tests.length; i++) {
            var r = this.testResults[tests[i].id];
            if (r) { done++; if (r === 'fail') fail++; else if (r === 'warn') warn++; else if (r === 'pass') pass++; }
        }
        var badge = document.getElementById('navcount-' + id);
        if (badge) {
            badge.textContent = done + '/' + tests.length;
            badge.className = 'diag-nav-count' + (fail ? ' has-fail' : (warn ? ' has-warn' : (done === tests.length && done ? ' all-pass' : '')));
        }
        var sum = document.getElementById('summary-' + id);
        if (sum) sum.textContent = pass + ' pass · ' + warn + ' warn · ' + fail + ' fail';
    }
    
    finishRun(label) {
        if (this._elapsedTimer) { clearInterval(this._elapsedTimer); this._elapsedTimer = null; }
        this.updateElapsed();
        var results = [];
        for (var key in this.testResults) results.push(this.testResults[key]);
        var passed = results.filter(function(t){ return t === 'pass'; }).length;
        var failed = results.filter(function(t){ return t === 'fail'; }).length;
        var warnings = results.filter(function(t){ return t === 'warn'; }).length;
        var stopped = this.cancelRequested;
        this.log('info', '═══════════════════════════════════════════════════════');
        this.log('info', '📊 ' + label + (stopped ? ' STOPPED' : ' COMPLETE') + ' — ' + passed + ' pass, ' + failed + ' fail, ' + warnings + ' warn');
        this.log('info', 'Duration: ' + this.fmtClock(Date.now() - this.startTime));
        this.log('info', '═══════════════════════════════════════════════════════');
        var etaEl = document.getElementById('diag-eta');
        if (etaEl) etaEl.innerHTML = '<i class="fas fa-flag-checkered"></i> Done';
        this.running = false; this.cancelRequested = false;
        this.setRunningUI(false);
        this.updateStats();
        for (var c = 0; c < this.categoryMeta.length; c++) { this.highlightCategory(this.categoryMeta[c].id, false); this.updateCategoryBadge(this.categoryMeta[c].id); }
    }
    
    clearResults() {
        this.testResults = {};
        var statusEls = document.querySelectorAll('.diag-test-status');
        for (var i = 0; i < statusEls.length; i++) {
            statusEls[i].className = 'diag-test-status pending';
            statusEls[i].innerHTML = '<i class="fas fa-circle"></i> Pending';
        }
        var testEls = document.querySelectorAll('.diag-test');
        for (var j = 0; j < testEls.length; j++) {
            testEls[j].className = 'diag-test';
        }
        var metaEls = document.querySelectorAll('[id^="meta-"]');
        for (var k = 0; k < metaEls.length; k++) {
            metaEls[k].textContent = '';
        }
        document.getElementById('diag-progress-bar').style.width = '0%';
        document.getElementById('system-health-indicator').className = 'diag-status-indicator';
        this.updateStats();
        this.log('info', 'All test results cleared');
    }
    
    toggleLogVerbosity() {
        this.verbose = !this.verbose;
        this.log('info', 'Verbose logging: ' + (this.verbose ? 'enabled' : 'disabled'));
    }
    
    exportResults() {
        var results = [];
        for (var key in this.testResults) {
            results.push(this.testResults[key]);
        }
        
        var report = {
            title: 'LionByteGG Master Diagnostics Report',
            generatedAt: new Date().toISOString(),
            url: window.location.href,
            userAgent: navigator.userAgent,
            viewport: window.innerWidth + 'x' + window.innerHeight,
            results: this.testResults,
            summary: {
                total: Object.keys(this.testResults).length,
                passed: results.filter(function(t) { return t === 'pass'; }).length,
                failed: results.filter(function(t) { return t === 'fail'; }).length,
                warnings: results.filter(function(t) { return t === 'warn'; }).length
            }
        };
        
        var blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'lionbyte-diagnostics-' + new Date().toISOString().split('T')[0] + '.json';
        a.click();
        URL.revokeObjectURL(url);
        
        this.log('success', 'Diagnostic report exported');
    }
}

// Initialize Diagnostics
window.diagnostics = new SystemDiagnostics();

// Close diagnostics on ESC
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && window.diagnostics && window.diagnostics.isOpen) {
        window.diagnostics.closeDiagnostics();
    }
});

console.log('LionByteGG Dashboard Utilities Loaded');
