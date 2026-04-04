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
                { id: 'auth-login', name: 'Login Page', endpoint: '/login', desc: 'GET /login' }
            ],
            bot: [
                { id: 'bot-stats', name: 'Bot Statistics', endpoint: '/api/stats', desc: 'GET /api/stats' },
                { id: 'bot-activity', name: 'Bot Activity', endpoint: '/api/bot/activity', desc: 'GET /api/bot/activity' },
                { id: 'bot-commands', name: 'Bot Commands', endpoint: '/api/commands', desc: 'GET /api/commands' }
            ],
            api: [
                { id: 'api-members', name: 'Members API', endpoint: '/api/members', desc: 'GET /api/members' },
                { id: 'api-analytics', name: 'Analytics API', endpoint: '/api/analytics', desc: 'GET /api/analytics' },
                { id: 'api-logs', name: 'Activity Logs', endpoint: '/api/activity-log', desc: 'GET /api/activity-log' },
                { id: 'api-search', name: 'Search API', endpoint: '/api/search?query=test', desc: 'GET /api/search' },
                { id: 'api-channels', name: 'Discord Channels', endpoint: '/api/discord/channels', desc: 'GET /api/discord/channels' }
            ],
            management: [
                { id: 'mgmt-tickets', name: 'Tickets API', endpoint: '/api/tickets', desc: 'GET /api/tickets' },
                { id: 'mgmt-guests', name: 'Guests API', endpoint: '/api/guests', desc: 'GET /api/guests' },
                { id: 'mgmt-user-records', name: 'User Records', endpoint: '/api/user-records', desc: 'GET /api/user-records' },
                { id: 'mgmt-varsity', name: 'Varsity Registrations', endpoint: '/api/varsity-registrations', desc: 'GET /api/varsity-registrations' },
                { id: 'mgmt-reaction-roles', name: 'Reaction Roles', endpoint: '/api/reaction-roles', desc: 'GET /api/reaction-roles' },
                { id: 'mgmt-arena', name: 'Arena Hours', endpoint: '/api/arena-hours', desc: 'GET /api/arena-hours' },
                { id: 'mgmt-vc', name: 'VC Generators', endpoint: '/api/vc-generators', desc: 'GET /api/vc-generators' }
            ],
            moderation: [
                { id: 'mod-templates', name: 'Moderation Templates', endpoint: '/api/moderation/templates', desc: 'GET /api/moderation/templates' },
                { id: 'mod-watchlist', name: 'Watchlist', endpoint: '/api/watchlist', desc: 'GET /api/watchlist' },
                { id: 'mod-flagged', name: 'Flagged Words', endpoint: '/api/flagged-words', desc: 'GET /api/flagged-words' }
            ],
            rosters: [
                { id: 'roster-list', name: 'Rosters List', endpoint: '/api/rosters', desc: 'GET /api/rosters' },
                { id: 'roster-matches', name: 'Match History', endpoint: '/api/rosters/matches', desc: 'GET /api/rosters/matches' },
                { id: 'roster-leaderboard', name: 'Leaderboard', endpoint: '/api/rosters/leaderboard', desc: 'GET /api/rosters/leaderboard' },
                { id: 'roster-audit', name: 'Audit Log', endpoint: '/api/rosters/audit-log', desc: 'GET /api/rosters/audit-log' },
                { id: 'roster-announcements', name: 'Announcements', endpoint: '/api/rosters/announcements', desc: 'GET /api/rosters/announcements' },
                { id: 'roster-notifications', name: 'Notification Settings', endpoint: '/api/rosters/notification-settings', desc: 'GET /api/rosters/notification-settings' }
            ],
            shifts: [
                { id: 'shift-schedules', name: 'Schedules', endpoint: '/api/shifts/schedules', desc: 'GET /api/shifts/schedules' },
                { id: 'shift-offers', name: 'Shift Offers', endpoint: '/api/shifts/offers', desc: 'GET /api/shifts/offers' },
                { id: 'shift-trades', name: 'Trade Requests', endpoint: '/api/shifts/trades', desc: 'GET /api/shifts/trades' },
                { id: 'shift-timeoff', name: 'Time Off Requests', endpoint: '/api/shifts/timeoff', desc: 'GET /api/shifts/timeoff' },
                { id: 'shift-logs', name: 'Shift Logs', endpoint: '/api/shifts/logs', desc: 'GET /api/shifts/logs' },
                { id: 'shift-workers', name: 'Student Workers', endpoint: '/api/shifts/workers', desc: 'GET /api/shifts/workers' },
                { id: 'shift-stats', name: 'Shift Statistics', endpoint: '/api/shifts/stats', desc: 'GET /api/shifts/stats' },
                { id: 'shift-settings', name: 'Shift Settings', endpoint: '/api/shifts/settings', desc: 'GET /api/shifts/settings' }
            ],
            music: [
                { id: 'music-status', name: 'Music Bot Status', endpoint: '/api/music/status', desc: 'GET /api/music/status' },
                { id: 'music-stats', name: 'Music Statistics', endpoint: '/api/music/stats', desc: 'GET /api/music/stats' },
                { id: 'music-history', name: 'Play History', endpoint: '/api/music/history', desc: 'GET /api/music/history' },
                { id: 'music-top', name: 'Top Tracks', endpoint: '/api/music/top-tracks', desc: 'GET /api/music/top-tracks' },
                { id: 'music-commands', name: 'Music Commands', endpoint: '/api/music/commands', desc: 'GET /api/music/commands' },
                { id: 'music-panels', name: 'Music Panels', endpoint: '/api/music/panels', desc: 'GET /api/music/panels' },
                { id: 'music-quiz', name: 'Quiz Songs', endpoint: '/api/music/quiz/songs', desc: 'GET /api/music/quiz/songs' }
            ],
            external: [
                { id: 'ext-ggleap', name: 'GGLeap Status', endpoint: '/api/ggleap/status', desc: 'GET /api/ggleap/status' },
                { id: 'ext-ggleap-games', name: 'GGLeap Games', endpoint: '/api/ggleap/games', desc: 'GET /api/ggleap/games' },
                { id: 'ext-notifications', name: 'Live Notifications', endpoint: '/api/live-notifications', desc: 'GET /api/live-notifications' },
                { id: 'ext-jobs', name: 'Background Jobs', endpoint: '/api/jobs/progress', desc: 'GET /api/jobs/progress' }
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
                    '<button class="diag-btn diag-btn-primary" onclick="window.diagnostics.runFullDiagnostics()"><i class="fas fa-rocket"></i> Full System Check</button>' +
                    '<button class="diag-btn diag-btn-secondary" onclick="window.diagnostics.runQuickCheck()"><i class="fas fa-bolt"></i> Quick Check</button>' +
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
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'system\')"><i class="fas fa-microchip"></i> System Health</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'auth\')"><i class="fas fa-shield-alt"></i> Authentication</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'bot\')"><i class="fas fa-robot"></i> Bot Status</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'api\')"><i class="fas fa-plug"></i> Core APIs</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'management\')"><i class="fas fa-users-cog"></i> Management APIs</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'moderation\')"><i class="fas fa-gavel"></i> Moderation</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'rosters\')"><i class="fas fa-trophy"></i> Rosters & Teams</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'shifts\')"><i class="fas fa-calendar-alt"></i> Shift System</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'music\')"><i class="fas fa-music"></i> Music Bot</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'external\')"><i class="fas fa-cloud"></i> External Services</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'ui\')"><i class="fas fa-desktop"></i> UI & Frontend</button>' +
                        '<button class="diag-nav-btn" onclick="window.diagnostics.scrollTo(\'performance\')"><i class="fas fa-tachometer-alt"></i> Performance</button>' +
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
        const sections = [
            { id: 'system', icon: 'fa-microchip', title: 'System Health' },
            { id: 'auth', icon: 'fa-shield-alt', title: 'Authentication & Security' },
            { id: 'bot', icon: 'fa-robot', title: 'Discord Bot Status' },
            { id: 'api', icon: 'fa-plug', title: 'Core API Endpoints' },
            { id: 'management', icon: 'fa-users-cog', title: 'Management APIs' },
            { id: 'moderation', icon: 'fa-gavel', title: 'Moderation System' },
            { id: 'rosters', icon: 'fa-trophy', title: 'Rosters & Teams' },
            { id: 'shifts', icon: 'fa-calendar-alt', title: 'LionShift System' },
            { id: 'music', icon: 'fa-music', title: 'LionBeats Music Bot' },
            { id: 'external', icon: 'fa-cloud', title: 'External Services' },
            { id: 'ui', icon: 'fa-desktop', title: 'UI & Frontend' },
            { id: 'performance', icon: 'fa-tachometer-alt', title: 'Performance Metrics' }
        ];
        
        return sections.map(s => 
            '<div class="diag-section" id="diag-' + s.id + '">' +
                '<div class="diag-section-header"><h3><i class="fas ' + s.icon + '"></i> ' + s.title + '</h3>' +
                '<button class="diag-btn diag-btn-sm" onclick="window.diagnostics.runCategoryTests(\'' + s.id + '\')"><i class="fas fa-play"></i> Run</button></div>' +
                '<div class="diag-tests" id="tests-' + s.id + '"></div>' +
            '</div>'
        ).join('');
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
            var startTime = performance.now();
            var response = await fetch(test.endpoint);
            var duration = Math.round(performance.now() - startTime);
            
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
            this.testResults[test.id] = 'fail';
            this.updateTestStatus(test.id, 'fail', 'Network Error');
            this.log('error', '✗ ' + test.name + ' - ' + error.message);
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
        this.log('info', '▶ Running ' + category + ' tests...');
        for (var i = 0; i < tests.length; i++) {
            await this.runTest(tests[i]);
            await new Promise(function(r) { setTimeout(r, 50); });
        }
    }
    
    async runQuickCheck() {
        this.log('info', '═══════════════════════════════════════');
        this.log('info', '⚡ QUICK SYSTEM CHECK');
        this.log('info', '═══════════════════════════════════════');
        
        this.testResults = {};
        var indicatorEl = document.getElementById('system-health-indicator');
        indicatorEl.className = 'diag-status-indicator checking';
        
        var quickTests = [
            this.testDefinitions.system[0],
            this.testDefinitions.auth[0],
            this.testDefinitions.bot[0],
            this.testDefinitions.api[0]
        ];
        
        for (var i = 0; i < quickTests.length; i++) {
            await this.runTest(quickTests[i]);
        }
        
        this.log('info', '═══════════════════════════════════════');
        this.log('info', '⚡ Quick check complete');
        this.log('info', '═══════════════════════════════════════');
    }
    
    async runFullDiagnostics() {
        this.log('info', '═══════════════════════════════════════════════════════');
        this.log('info', '🚀 FULL SYSTEM DIAGNOSTICS');
        this.log('info', 'Started at: ' + new Date().toISOString());
        this.log('info', '═══════════════════════════════════════════════════════');
        
        this.testResults = {};
        this.startTime = Date.now();
        var indicatorEl = document.getElementById('system-health-indicator');
        indicatorEl.className = 'diag-status-indicator checking';
        
        var overallEl = document.getElementById('diag-overall');
        overallEl.className = 'diag-overall-status running';
        overallEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running full diagnostics...';
        
        var categories = Object.keys(this.testDefinitions);
        for (var i = 0; i < categories.length; i++) {
            await this.runCategoryTests(categories[i]);
        }
        
        var duration = Date.now() - this.startTime;
        document.getElementById('diag-duration').textContent = duration + 'ms';
        
        var results = [];
        for (var key in this.testResults) {
            results.push(this.testResults[key]);
        }
        var passed = results.filter(function(t) { return t === 'pass'; }).length;
        var failed = results.filter(function(t) { return t === 'fail'; }).length;
        var warnings = results.filter(function(t) { return t === 'warn'; }).length;
        
        this.log('info', '═══════════════════════════════════════════════════════');
        this.log('info', '📊 DIAGNOSTICS COMPLETE');
        this.log('info', 'Duration: ' + duration + 'ms');
        this.log('info', 'Results: ' + passed + ' passed, ' + failed + ' failed, ' + warnings + ' warnings');
        this.log('info', '═══════════════════════════════════════════════════════');
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
