// Backend Database API Implementation to replace LocalDatabase
class BackendDatabase {
    constructor() {
        /* @tweakable API base URL for backend database */
        this.baseUrl = '/api';
        
        /* @tweakable request timeout in milliseconds - reduced for better UX */
        this.requestTimeout = 8000;
        
        /* @tweakable whether to enable database API debugging */
        this.debugMode = true;
        
        /* @tweakable whether to log JavaScript loading and initialization errors */
        this.enableScriptDebugging = true;
        
        /* @tweakable maximum retry attempts for failed requests */
        this.maxRetries = 3;
        
        /* @tweakable delay between retry attempts in milliseconds */
        this.retryDelay = 1000;
        
        this.collections = {};
        this.subscribers = {};
    }

    collection(name) {
        if (!this.collections[name]) {
            this.collections[name] = new BackendCollection(name, this);
        }
        return this.collections[name];
    }
}

class BackendCollection {
    constructor(name, database) {
        this.name = name;
        this.database = database;
        this.subscribers = [];
        this.filters = {};
        this.cachedData = [];
        this.lastFetchTime = 0;
        
        /* @tweakable cache duration in milliseconds */
        this.cacheTimeout = 5000;
    }

    async makeRequest(method, path = '', data = null) {
        const url = `${this.database.baseUrl}/${this.name}${path}`;
        
        for (let attempt = 1; attempt <= this.database.maxRetries; attempt++) {
            const methodUpper = method.toUpperCase();
            const shouldUseTimeout = this.database.requestTimeout > 0 && !['POST', 'PUT'].includes(methodUpper);
            let controller = null;
            let timeoutId = null;
            try {
                const options = {
                    method: method,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    credentials: 'include'
                };

                if (shouldUseTimeout) {
                    controller = new AbortController();
                    timeoutId = setTimeout(() => controller.abort(), this.database.requestTimeout);
                    options.signal = controller.signal;
                }

                if (sessionToken) {
                    options.headers['Authorization'] = `Bearer ${sessionToken}`;
                }
                
                if (data) {
                    options.body = JSON.stringify(data);
                }
                
                if (this.database.debugMode) {
                    console.log(`REQUEST ${method} ${url}`, data ? data : '');
                }
                
                const response = await fetch(url, options);
                if (timeoutId) {
                    clearTimeout(timeoutId);
                }

                if (!response.ok) {
                    const rawBody = await response.text().catch(() => '');
                    let parsedData = null;
                    if (rawBody) {
                        try {
                            parsedData = JSON.parse(rawBody);
                        } catch (parseError) {
                            // Leave parsedData as null if body is not valid JSON
                        }
                    }

                    const error = new Error(`HTTP ${response.status} ${response.statusText || ''}`.trim());
                    error.status = response.status;
                    error.statusText = response.statusText;
                    error.body = rawBody;
                    error.data = parsedData;
                    error.response = response;
                    throw error;
                }

                const result = await response.json();
                
                if (this.database.debugMode) {
                    console.log(`SUCCESS ${method} ${url} success`, result);
                }
                
                return result;
                
            } catch (error) {
                if (timeoutId) {
                    clearTimeout(timeoutId);
                }

                let isTimeoutError = false;
                if (error.name === 'AbortError') {
                    console.error(`TIMEOUT ${method} ${url} timed out after ${this.database.requestTimeout}ms`);
                    const timeoutError = new Error(`Request timed out after ${this.database.requestTimeout}ms`);
                    timeoutError.name = 'TimeoutError';
                    error = timeoutError;
                    isTimeoutError = true;
                } else if (error.name === 'TimeoutError' || /timed out/i.test(error.message)) {
                    isTimeoutError = true;
                }

                const shouldStopRetrying = attempt === this.database.maxRetries || (methodUpper === 'PUT' && isTimeoutError);

                if (shouldStopRetrying) {
                    console.error(`ERROR ${method} ${url} failed after ${attempt} attempts:`, error);
                    throw error;
                } else {
                    console.warn(`WARNING ${method} ${url} attempt ${attempt} failed, retrying...`, error.message);
                    await new Promise(resolve => setTimeout(resolve, this.database.retryDelay));
                }
            }
        }
    }

    async getList(params = {}) {
        const queryString = new URLSearchParams(params).toString();
        try {
            // Check cache validity for unfiltered requests
            const now = Date.now();
            if (!queryString && this.cachedData.length > 0 && now - this.lastFetchTime < this.cacheTimeout) {
                return this.applyFilters(this.cachedData);
            }

            const data = await this.makeRequest('GET', queryString ? `?${queryString}` : '');
            if (!queryString) {
                this.cachedData = data || [];
                this.lastFetchTime = now;
                return this.applyFilters(this.cachedData);
            }

            return this.applyFilters(data || []);
        } catch (error) {
            console.error(`Error fetching ${this.name}:`, error);
            if (!queryString) {
                return this.applyFilters(this.cachedData); // Return cached data on error for unfiltered requests
            }
            return this.applyFilters([]);
        }
    }

    applyFilters(data) {
        if (Object.keys(this.filters).length === 0) {
            return data;
        }
        
        return data.filter(item => {
            return Object.entries(this.filters).every(([key, value]) => {
                return item[key] === value;
            });
        });
    }

    async create(data) {
        try {
            const result = await this.makeRequest('POST', '', data);
            
            // Invalidate cache
            this.lastFetchTime = 0;
            
            // Notify subscribers
            setTimeout(() => this.notifySubscribers(), 100);
            
            return result;
        } catch (error) {
            console.error(`Error creating ${this.name}:`, error);
            throw error;
        }
    }

    async update(id, data) {
        try {
            const result = await this.makeRequest('PUT', `/${id}`, data);
            
            // Invalidate cache
            this.lastFetchTime = 0;
            
            // Notify subscribers
            setTimeout(() => this.notifySubscribers(), 100);
            
            return result;
        } catch (error) {
            console.error(`Error updating ${this.name}:`, error);
            throw error;
        }
    }

    async delete(id) {
        try {
            const result = await this.makeRequest('DELETE', `/${id}`);
            
            // Invalidate cache
            this.lastFetchTime = 0;
            
            // Notify subscribers
            setTimeout(() => this.notifySubscribers(), 100);
            
            return result;
        } catch (error) {
            console.error(`Error deleting ${this.name}:`, error);
            throw error;
        }
    }

    filter(filterObj) {
        const filteredCollection = new BackendCollection(this.name, this.database);
        filteredCollection.filters = { ...this.filters, ...filterObj };
        filteredCollection.cachedData = this.cachedData;
        filteredCollection.lastFetchTime = this.lastFetchTime;
        return filteredCollection;
    }

    subscribe(callback) {
        this.subscribers.push(callback);
        
        // Call immediately with current data
        this.getList().then(data => {
            try {
                callback(data);
            } catch (error) {
                console.error('Error in subscriber callback:', error);
            }
        });
        
        // Return unsubscribe function
        return () => {
            const index = this.subscribers.indexOf(callback);
            if (index > -1) {
                this.subscribers.splice(index, 1);
            }
        };
    }

    async notifySubscribers() {
        try {
            const data = await this.getList();
            this.subscribers.forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error('Error in subscriber callback:', error);
                }
            });
        } catch (error) {
            console.error('Error notifying subscribers:', error);
        }
    }
}

// Global variables and initialization
/* @tweakable prefer backend API over local storage */
const USE_BACKEND_DATABASE = true;
if (USE_BACKEND_DATABASE) {
    if (!window.room || !(window.room instanceof BackendDatabase)) {
        window.room = new BackendDatabase();
        console.log('SUCCESS room initialized with BackendDatabase');
    }
}
const room = window.room;

// Global cache for holiday dates (ISO YYYY-MM-DD)
const holidayDates = new Set();

// Standard number of working hours that make up a full leave day.
const WORK_HOURS_PER_DAY = 8;
// Default working hours applied to leave requests when specific times are unavailable.
const DEFAULT_WORKDAY_START_TIME = '06:30';
const DEFAULT_WORKDAY_END_TIME = '15:00';

// Authentication globals
let currentUserType = null;
let currentUser = null;
let sessionToken = null;

// Track whether holiday form handlers have been initialized
let holidayFormInitialized = false;

// Track admin history requests to ignore stale responses
let adminHistoryRequestId = 0;

/* @tweakable sessionStorage keys for authentication persistence */
const AUTH_TYPE_KEY = 'elms_auth_type';
const AUTH_USER_KEY = 'elms_auth_user';
const AUTH_TOKEN_KEY = 'elms_session_token';

/* @tweakable whether to enable detailed employee form submission debugging */
const enableEmployeeFormDebugging = true;

/* @tweakable maximum retry attempts for employee form submission */
const maxEmployeeFormRetries = 3;

/* @tweakable delay between employee form submission retries in milliseconds */
const employeeFormRetryDelay = 1000;

/* @tweakable whether to show visual feedback during employee creation */
const showEmployeeCreationFeedback = true;

/* @tweakable timeout for employee form submission in milliseconds - reduced for better responsiveness */
const employeeFormTimeout = 5000;

// @tweakable bootstrap employee data (balances, history) on successful login
const ENABLE_EMPLOYEE_BOOTSTRAP_ON_LOGIN = true;

// Minimal LeaveBalanceAPI used across UI
window.LeaveBalanceAPI = {
    /* @tweakable show detailed admin balance in tables */
    showDetailedAdminBalance: true,
    /* @tweakable show balance history column in admin view */
    showBalanceHistoryCount: false,
    /* @tweakable low-balance threshold in days for color cue */
    lowBalanceThreshold: 3,
    /* @tweakable employee balance cache for performance */
    employeeBalanceCache: new Map(),
    /* @tweakable cache timeout for employee balances in milliseconds */
    employeeBalanceCacheTimeout: 30000,

    /* @tweakable clear balance cache for specific employee to force fresh data */
    clearEmployeeBalanceCache(employeeId = null) {
        if (employeeId) {
            this.employeeBalanceCache.delete(employeeId);
        } else {
            this.employeeBalanceCache.clear();
        }
    },

    async getEmployeeBalances(/* @tweakable employeeId to filter (null = all) */ employeeId = null) {
        /* @tweakable whether to use caching for employee balance requests */
        const useCaching = true;
        
        // Check cache if enabled and querying specific employee
        if (useCaching && employeeId) {
            const cacheKey = employeeId;
            const cached = this.employeeBalanceCache.get(cacheKey);
            
            if (cached && Date.now() - cached.timestamp < this.employeeBalanceCacheTimeout) {
                return cached.data.filter(b => b.employee_id === employeeId);
            }
        }
        
        const all = await room.collection('leave_balance').getList();
        
        // Update cache if enabled and we have data
        if (useCaching && employeeId && all.length > 0) {
            this.employeeBalanceCache.set(employeeId, {
                data: all,
                timestamp: Date.now()
            });
        }
        
        return employeeId ? all.filter(b => b.employee_id === employeeId) : all;
    },

    getBalanceColor(balance, kind) {
        if (!balance) return '#64748b';
        if (balance.remaining_days <= 0) return '#dc2626';
        if (balance.remaining_days <= this.lowBalanceThreshold) return '#ea580c';
        return kind === 'sick' ? '#065f46' : '#2563eb';
    },

    async setRemainingDays(/* @tweakable employee id */ employeeId, /* @tweakable balance type */ balanceType, /* @tweakable new remaining days */ remaining) {
        const balances = await this.getEmployeeBalances(employeeId);
        const bal = balances.find(b => b.balance_type === balanceType);
        if (!bal) throw new Error(`Balance not found for ${balanceType}`);

        const result = await room.collection('leave_balance').update(bal.id, { remaining_days: parseFloat(remaining) });

        // Clear cached balances and refresh employee list
        this.clearEmployeeBalanceCache(employeeId);
        await loadEmployeeList();

        return result;
    }
};

const SERVICE_LENGTH_MAP = {
    '1-3': 5,
    '4-7': 10,
    '8+': 15
};

// Handle login and app initialization
document.addEventListener('DOMContentLoaded', function() {
    /* @tweakable whether to show debug messages during login flow initialization */
    const debugLoginFlow = true;
    
    /* @tweakable whether to validate app container visibility on page load */
    const validateInitialVisibility = true;
    
    /* @tweakable delay in milliseconds before setting up login handlers */
    const loginHandlerDelay = 500;
    
    /* @tweakable maximum retry attempts for finding login elements */
    const maxLoginElementRetries = 5;
    
    /* @tweakable delay between retries when finding login elements */
    const loginElementRetryDelay = 200;
    
    /* @tweakable whether to enable extensive button debugging */
    const enableButtonDebugging = false;
    
    /* @tweakable whether to add visual debugging indicators to buttons */
    const addVisualDebugging = false;
    
    /* @tweakable whether to log DOM state during initialization */
    const logDOMState = true;
    
    if (debugLoginFlow) {
        console.log('START Initializing Employee Leave Management System...');
        console.log('INFO Page Load Debug Info:');
        console.log('- Current URL:', window.location.href);
        console.log('- DOM Ready State:', document.readyState);
        console.log('- Script Loading Time:', new Date().toISOString());
    }

    initEntryButtons();
    restoreAuthenticationState();
    
    // Enhanced DOM state logging
    if (logDOMState) {
        console.log('INFO DOM State Check:');
        console.log('- Entry Container:', document.getElementById('entryContainer'));
        console.log('- Employee Entry Button:', document.getElementById('employeeEntryBtn'));
        console.log('- Admin Entry Button:', document.getElementById('adminEntryBtn'));
        console.log('- Employee Login Container:', document.getElementById('employeeLoginContainer'));
        console.log('- Admin Login Container:', document.getElementById('adminLoginContainer'));
        console.log('- App Container:', document.getElementById('appContainer'));
    }
    
    // Ensure proper initial state - only entry selection should be visible
    if (validateInitialVisibility) {
        document.getElementById('appContainer').style.display = 'none';
        document.getElementById('employeeLoginContainer').style.display = 'none';
        document.getElementById('adminLoginContainer').style.display = 'none';
    }

    // Attach tab navigation handlers
    const tabLeaveRequest = document.getElementById('tabLeaveRequest');
    if (tabLeaveRequest) {
        tabLeaveRequest.addEventListener('click', () => switchTab('leave-request'));
    }
    const tabCheckHistory = document.getElementById('tabCheckHistory');
    if (tabCheckHistory) {
        tabCheckHistory.addEventListener('click', () => switchTab('check-history'));
    }
    const tabEmployeeManagement = document.getElementById('tabEmployeeManagement');
    if (tabEmployeeManagement) {
        tabEmployeeManagement.addEventListener('click', () => switchTab('employee-management'));
    }
    const tabApplicationStatus = document.getElementById('tabApplicationStatus');
    if (tabApplicationStatus) {
        tabApplicationStatus.addEventListener('click', () => switchTab('application-status'));
    }
    const tabHolidayDates = document.getElementById('tabHolidayDates');
    if (tabHolidayDates) {
        tabHolidayDates.addEventListener('click', () => switchTab('holiday-dates'));
    }
    const tabAdminHistory = document.getElementById('tabAdminHistory');
    if (tabAdminHistory) {
        tabAdminHistory.addEventListener('click', () => switchTab('admin-history'));
    }
    const resetBtn = document.getElementById('resetBalancesBtn');
    if (resetBtn) resetBtn.addEventListener('click', resetAllLeaveBalances);

    const errorModalClose = document.getElementById('errorModalClose');
    if (errorModalClose) {
        errorModalClose.addEventListener('click', closeErrorModal);
    }

    const errorModalOk = document.getElementById('errorModalOk');
    if (errorModalOk) {
        errorModalOk.addEventListener('click', closeErrorModal);
    }

    const timeWarningClose = document.getElementById('timeWarningClose');
    if (timeWarningClose) {
        timeWarningClose.addEventListener('click', closeTimeWarningModal);
    }

    const timeWarningOk = document.getElementById('timeWarningOk');
    if (timeWarningOk) {
        timeWarningOk.addEventListener('click', closeTimeWarningModal);
    }

    const editModalClose = document.getElementById('editModalClose');
    if (editModalClose) {
        editModalClose.addEventListener('click', closeEditModal);
    }

    const editModalCancel = document.getElementById('editModalCancel');
    if (editModalCancel) {
        editModalCancel.addEventListener('click', closeEditModal);
    }
    
    // Add visual debugging indicators to buttons if enabled
    if (addVisualDebugging && enableButtonDebugging) {
        setTimeout(() => {
            const employeeBtn = document.getElementById('employeeEntryBtn');
            const adminBtn = document.getElementById('adminEntryBtn');
            
            if (employeeBtn) {
                employeeBtn.style.border = '2px dashed red';
                employeeBtn.title = 'DEBUG: Employee button found and marked';
                console.log('DEBUG Visual debug marker added to employee button');
            } else {
                console.error('ERROR Employee button not found for visual debugging');
            }
            
            if (adminBtn) {
                adminBtn.style.border = '2px dashed red';
                adminBtn.title = 'DEBUG: Admin button found and marked';
                console.log('DEBUG Visual debug marker added to admin button');
            } else {
                console.error('ERROR Admin button not found for visual debugging');
            }
        }, 100);
    }
    
    // Ensure button handlers work as backup
    if (enableButtonDebugging) {
        setTimeout(() => {
            const employeeBtn = document.getElementById('employeeEntryBtn');
            const adminBtn = document.getElementById('adminEntryBtn');

            console.log('INFO Setting up backup button handlers...');

            if (employeeBtn) {
                employeeBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    console.log('INFO Backup employee handler triggered');
                    showEmployeeLogin();
                });
                console.log('SUCCESS Employee button handler confirmed');
            } else {
                console.error('ERROR Employee button not found!');
            }

            if (adminBtn) {
                adminBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    console.log('INFO Backup admin handler triggered');
                    showAdminLogin();
                });
                console.log('SUCCESS Admin button handler confirmed');
            } else {
                console.error('ERROR Admin button not found!');
            }
        }, 200);
    }
    
    // **FIX: Attach critical form handlers immediately to prevent race condition**
    setupCriticalFormHandlers();
    
    // Initialize local database connection (but don't show the app yet)
    initializeLocalDatabase();
    
    // Check URL parameters for direct login type
    const urlParams = new URLSearchParams(window.location.search);
    const loginType = urlParams.get('type');
    
    if (loginType === 'employee') {
        showEmployeeLogin();
    } else if (loginType === 'admin') {
        showAdminLogin();
    } else {
        // Show entry point selection
        showEntrySelection();
    }
    
    // Setup login handlers with enhanced retry logic
    const setupHandlersWithRetry = async (retryCount = 0) => {
        try {
            await setupLoginHandlers();
            if (debugLoginFlow) {
                console.log('SUCCESS Login handlers setup completed successfully');
            }
        } catch (error) {
            console.error('ERROR Error setting up login handlers:', error);
            if (retryCount < maxLoginElementRetries) {
                console.log(`INFO Retrying login handler setup (attempt ${retryCount + 1})...`);
                setTimeout(() => setupHandlersWithRetry(retryCount + 1), loginElementRetryDelay);
            } else {
                console.error('ERROR Failed to setup login handlers after maximum retries');
                // Try direct button attachment as fallback
                setupLoginButtonsFallback();
            }
        }
    };
    
    setTimeout(() => {
        setupHandlersWithRetry();
    }, loginHandlerDelay);
    
    if (debugLoginFlow) {
        console.log('SUCCESS Login flow initialization completed');
    }
});

function updatePrivilegeLeave(rangeId, targetId) {
    const range = document.getElementById(rangeId);
    const target = document.getElementById(targetId);
    if (!range || !target) return;

    const mapping = {
        '1-3': 5,
        '4-7': 10,
        '8+': 15
    };

    target.value = mapping[range.value] || '';
}

// **NEW: Set up critical form handlers immediately to prevent race condition**
function setupCriticalFormHandlers() {
    /* @tweakable whether to enable immediate form handler setup debugging */
    const debugImmediateSetup = true;
    
    if (debugImmediateSetup) {
        console.log('START Setting up critical form handlers immediately...');
    }
    
    // Set up employee form handler immediately
    const employeeForm = document.getElementById('employeeForm');
    if (employeeForm) {
        employeeForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            if (debugImmediateSetup) {
                console.log('SUCCESS Employee form submitted via immediate handler');
            }
            
            await handleEmployeeFormSubmit();
        });
        
        if (debugImmediateSetup) {
            console.log('SUCCESS Employee form submit handler attached immediately');
        }

        const serviceLengthSelect = document.getElementById('serviceLength');
        if (serviceLengthSelect) {
            serviceLengthSelect.addEventListener('change', function() {
                updatePrivilegeLeave('serviceLength', 'annualLeave');
            });

            // Set default PL days based on the initial service length selection
            updatePrivilegeLeave('serviceLength', 'annualLeave');

            if (debugImmediateSetup) {
                console.log('SUCCESS Service length change handler attached immediately');
            }
        }
    }
    
    // Set up vacation form handler immediately
    const vacationForm = document.getElementById('vacationForm');
    if (vacationForm) {
        vacationForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();

            if (debugImmediateSetup) {
                console.log('SUCCESS Vacation form submitted via immediate handler');
            }

            const formData = new FormData(e.target);
            const startDate = formData.get('startDate');
            const endDate = formData.get('endDate');
            const startTime = formData.get('startTime') || null;
            const endTime = formData.get('endTime') || null;
            const durationText = document.getElementById('durationText');

            const validation = validateSingleDayTimeWindow(startDate, endDate, startTime, endTime);
            showTimeWarningIfNeeded(validation);
            if (!validation.valid) {
                if (durationText) {
                    durationText.textContent = validation.message;
                }
                return;
            }

            const totalHours = calculateTotalHours(startDate, endDate, startTime, endTime);
            const returnDate = determineReturnDate(endDate, totalHours);
            const message = returnDate
                ? `You are expected to return on ${returnDate}. Continue?`
                : 'Submit leave request?';

            if (confirm(message)) {
                await submitLeaveApplication(e, returnDate);
            }
        });

        vacationForm.addEventListener('reset', function() {
            updateEmployeeInfo();
        });

        if (debugImmediateSetup) {
            console.log('SUCCESS Vacation form submit handler attached immediately');
        }
    }

    // Set up edit employee form handler immediately
    const editEmployeeForm = document.getElementById('editEmployeeForm');
    if (editEmployeeForm) {
        editEmployeeForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();

            if (debugImmediateSetup) {
                console.log('SUCCESS Edit employee form submitted via immediate handler');
            }

            try {
                const formData = new FormData(editEmployeeForm);
                const employeeId = editEmployeeForm.dataset.employeeId;

                const updatedData = {
                    first_name: formData.get('editFirstName'),
                    surname: formData.get('editSurname'),
                    personal_email: formData.get('editPersonalEmail'),
                    annual_leave: parseInt(formData.get('editAnnualLeave')) || 0,
                    sick_leave: parseInt(formData.get('editSickLeave')) || 0,
                    remaining_privilege_leave:
                        parseFloat(formData.get('editRemainingPrivilege')) || 0,
                    remaining_sick_leave:
                        parseFloat(formData.get('editRemainingSick')) || 0
                };

                await room.collection('employee').update(employeeId, updatedData);

                await loadEmployeeList();
                await loadEmployeeSummary();
                closeEditModal();
                alert('Employee updated successfully');
            } catch (error) {
                console.error('Error updating employee:', error);
                alert(`Error updating employee: ${error.message}`);
            }
        });

        const editServiceLength = document.getElementById('editServiceLength');
        if (editServiceLength) {
            editServiceLength.addEventListener('change', function() {
                const annualInput = document.getElementById('editAnnualLeave');
                const mapped = SERVICE_LENGTH_MAP[this.value];
                annualInput.value = mapped !== undefined ? mapped : '';
            });
        }

        if (debugImmediateSetup) {
            console.log('SUCCESS Edit employee form submit handler attached immediately');
        }
    }
    
    if (debugImmediateSetup) {
        console.log('SUCCESS Critical form handlers setup completed');
    }
}

function setupLoginButtonsFallback() {
    /* @tweakable whether to enable fallback button setup debugging */
    const debugFallback = true;
    
    if (debugFallback) {
        console.log('INFO Setting up fallback login button handlers...');
    }
    
    const employeeBtn = document.getElementById('employeeEntryBtn');
    const adminBtn = document.getElementById('adminEntryBtn');

    if (employeeBtn) {
        employeeBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showEmployeeLogin();
        });
    }

    if (adminBtn) {
        adminBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showAdminLogin();
        });
    }
}

function initializeLocalDatabase() {
    /* @tweakable database initialization timeout in milliseconds */
    const dbInitTimeout = 3000;
    
    console.log('INFO Initializing local database connection...');
    
    if (window.room) {
        console.log('SUCCESS Database connection ready');
    } else {
        console.warn('WARNING Database connection not available yet');
    }
}

function restoreAuthenticationState() {
    /* @tweakable authentication state restoration debugging */
    const debugAuthRestore = true;
    try {
        const savedType = sessionStorage.getItem(AUTH_TYPE_KEY);
        const savedUser = sessionStorage.getItem(AUTH_USER_KEY);
        const savedToken = sessionStorage.getItem(AUTH_TOKEN_KEY);

        if (savedType && savedUser) {
            const canRestore = savedType === 'admin' || savedToken;
            if (canRestore) {
                currentUserType = savedType;
                currentUser = JSON.parse(savedUser);
                sessionToken = savedToken;

                if (debugAuthRestore) {
                    console.log('SUCCESS Authentication state restored:', { type: currentUserType, user: currentUser });
                }
                showMainApp();
            }
        }
    } catch (error) {
        console.error('Error restoring auth state:', error);
        clearPersistedAuthState();
    }
}

function clearPersistedAuthState() {
    /* @tweakable whether to clear all auth-related sessionStorage items */
    const clearAllAuthData = true;

    if (clearAllAuthData) {
        sessionStorage.removeItem(AUTH_TYPE_KEY);
        sessionStorage.removeItem(AUTH_USER_KEY);
        sessionStorage.removeItem(AUTH_TOKEN_KEY);
    }
}

// Show functions
function showEntrySelection() {
    document.getElementById('entryContainer').style.display = 'block';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'none';
}

function initEntryButtons() {
    const employeeBtn = document.getElementById('employeeEntryBtn');
    const adminBtn = document.getElementById('adminEntryBtn');

    if (employeeBtn) {
        employeeBtn.addEventListener('click', showEmployeeLogin);
    } else {
        console.error('employeeEntryBtn not found');
    }

    if (adminBtn) {
        adminBtn.addEventListener('click', showAdminLogin);
    } else {
        console.error('adminEntryBtn not found');
    }
}

function showEmployeeLogin() {
    /* @tweakable whether to log navigation to employee login */
    const logNavigation = true;

    if (logNavigation) {
        console.log('INFO Navigating to employee login');
    }

    const employeeForm = document.getElementById('loginEmployeeForm');
    if (employeeForm) {
        employeeForm.reset();
    }

    document.getElementById('entryContainer').style.display = 'none';
    document.getElementById('employeeLoginContainer').style.display = 'block';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'none';
}

function showAdminLogin() {
    /* @tweakable whether to log navigation to admin login */
    const logNavigation = true;

    if (logNavigation) {
        console.log('INFO Navigating to admin login');
    }

    const adminForm = document.getElementById('loginAdminForm');
    if (adminForm) {
        adminForm.reset();
    }

    document.getElementById('entryContainer').style.display = 'none';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'block';
    document.getElementById('appContainer').style.display = 'none';
}

async function setupLoginHandlers() {
    /* @tweakable login handler setup configuration */
    const enableDetailedLogging = true;
    const validateFormElements = true;
    
    if (enableDetailedLogging) {
        console.log('INFO Setting up login form handlers...');
    }
    
    // Employee login form
    const employeeForm = document.getElementById('loginEmployeeForm');
    if (employeeForm) {
        employeeForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const email = document.getElementById('loginEmployeeEmail').value.trim();
            
            if (email) {
                await loginEmployee(email);
            }
        });
        
        if (enableDetailedLogging) {
            console.log('SUCCESS Employee login form handler attached');
        }
    }
    
    // Admin login form
    const adminForm = document.getElementById('loginAdminForm');
    if (adminForm) {
        adminForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('loginAdminUsername').value.trim();
            const password = document.getElementById('loginAdminPassword').value.trim();
            
            if (username && password) {
                await loginAdmin(username, password);
            }
        });
        
        if (enableDetailedLogging) {
            console.log('SUCCESS Admin login form handler attached');
        }
    }
    
    // Back button handlers
    const backFromEmployee = document.getElementById('backToEntryFromEmployee');
    const backFromAdmin = document.getElementById('backToEntryFromAdmin');
    
    if (backFromEmployee) {
        backFromEmployee.addEventListener('click', showEntrySelection);
    }
    
    if (backFromAdmin) {
        backFromAdmin.addEventListener('click', showEntrySelection);
    }
    
    // Logout handler
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
}

function generatePreviewApplicationId() {
    const datePart = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const randomPart = Math.random().toString(36).substring(2, 10).toUpperCase();
    return `APP-${datePart}-${randomPart}`;
}

async function updateEmployeeInfo() {
    const nameEl = document.getElementById('employeeDisplayName');
    if (!nameEl) {
        console.warn('employeeDisplayName element not found');
    } else if (currentUser) {
        nameEl.textContent = `${currentUser.first_name} ${currentUser.surname}`;
    }

    const idPreviewEl = document.getElementById('applicationIdPreview');
    if (!idPreviewEl) {
        console.warn('applicationIdPreview element not found');
    } else {
        let previewId = generatePreviewApplicationId();
        try {
            // Request a server-generated ID for consistency with stored applications
            const resp = await fetch('/api/next_application_id', {
                headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {},
                credentials: 'include'
            });
            if (resp.ok) {
                const data = await resp.json();
                previewId = data.application_id || previewId;
            }
        } catch (err) {
            // Use generated previewId on error or if endpoint not available
        }
        idPreviewEl.textContent = previewId;
    }

    // Update leave balance display for logged in employee
    if (currentUser && currentUser.id) {
        await updateLeaveBalanceDisplay();
    }
}

// Fetch and render remaining leave balances for the current employee
async function updateLeaveBalanceDisplay() {
    const container = document.getElementById('leaveBalanceDisplay');
    if (!currentUser || !container) {
        return;
    }

    try {
        const resp = await fetch(`/api/leave_balance?employee_id=${currentUser.id}`, {
            headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {},
            credentials: 'include'
        });
        if (!resp.ok) throw new Error('Failed to fetch leave balances');
        const balances = await resp.json();

        const priv = balances.find(b => b.balance_type === 'PRIVILEGE');
        const sick = balances.find(b => b.balance_type === 'SICK');

        const privEl = document.getElementById('privilegeLeaveBalance');
        const sickEl = document.getElementById('sickLeaveBalance');
        if (privEl) {
            privEl.textContent = priv ? `${priv.remaining_days} days` : '-- days';
        }
        if (sickEl) {
            sickEl.textContent = sick ? `${sick.remaining_days} days` : '-- days';
        }

        container.style.display = 'block';
    } catch (err) {
        console.error('Error loading leave balances:', err);
        container.style.display = 'none';
    }
}

async function loginEmployee(email) {
    /* @tweakable employee login timeout in milliseconds */
    const loginTimeout = 5000;
    
    try {
        showLoading();
        
        const response = await fetch('/api/bootstrap_employee', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email }),
            credentials: 'include'
        });
        
        if (!response.ok) {
            throw new Error(`Login failed: ${response.status}`);
        }
        
        const data = await response.json();

        currentUserType = 'employee';
        currentUser = data.employee;
        sessionToken = data.token || data.sessionToken || null;
        await updateEmployeeInfo();

        sessionStorage.setItem(AUTH_TYPE_KEY, currentUserType);
        sessionStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
        if (sessionToken) {
            sessionStorage.setItem(AUTH_TOKEN_KEY, sessionToken);
        }
        
        hideLoading();
        showMainApp();
        
    } catch (error) {
        hideLoading();
        alert(`Login failed: ${error.message}`);
    }
}

async function loginAdmin(username, password) {
    try {
        showLoading();

        const resp = await fetch('/api/login_admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ username, password })
        });

        if (!resp.ok) {
            throw new Error('Invalid credentials');
        }

        currentUserType = 'admin';
        currentUser = { username: username, first_name: 'Administrator', email: 'admin@company.com' };
        sessionToken = null;
        sessionStorage.setItem(AUTH_TYPE_KEY, currentUserType);
        sessionStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
        sessionStorage.removeItem(AUTH_TOKEN_KEY);

        hideLoading();
        showMainApp();
    } catch (error) {
        hideLoading();
        alert(`Login failed: ${error.message}`);
    }
}

async function logoutAdmin() {
    try {
        await fetch('/api/logout_admin', {
            method: 'POST',
            credentials: 'include'
        });
    } catch (error) {
        console.error('Error logging out admin:', error);
    }
}

function showMainApp() {
    document.getElementById('entryContainer').style.display = 'none';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'block';

    // Ensure user-specific fields are updated whenever the main app is shown
    updateEmployeeInfo();

    configureTabsForUser();
    displayWelcome();
    initializeApp();
}

function configureTabsForUser() {
    const isAdmin = currentUserType === 'admin';

    document.getElementById('tabEmployeeManagement').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('tabApplicationStatus').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('tabHolidayDates').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('tabAdminHistory').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('adminSection').style.display = isAdmin ? 'block' : 'none';

    // Toggle visibility for employee-specific tabs based on user role
    document.getElementById('tabLeaveRequest').style.display = isAdmin ? 'none' : 'block';
    document.getElementById('tabCheckHistory').style.display = isAdmin ? 'none' : 'block';

    // Hide tab content sections that shouldn't be visible for the current role
    document.getElementById('employee-management').style.display = isAdmin ? '' : 'none';
    document.getElementById('application-status').style.display = isAdmin ? '' : 'none';
    document.getElementById('holiday-dates').style.display = isAdmin ? '' : 'none';
    document.getElementById('admin-history').style.display = isAdmin ? '' : 'none';
    document.getElementById('leave-request').style.display = isAdmin ? 'none' : '';
    document.getElementById('check-history').style.display = isAdmin ? 'none' : '';

    // Ensure the active tab is one the user can access
    const activeTab = document.querySelector('.tab-content.active');
    if (activeTab && activeTab.style.display === 'none') {
        switchTab(isAdmin ? 'employee-management' : 'leave-request');
    }
}

function displayWelcome() {
    const welcomeContainer = document.getElementById('welcomeContainer');
    const welcomeName = document.getElementById('welcomeName');
    
    if (currentUser) {
        const displayName = currentUser.first_name ? 
            `Welcome, ${currentUser.first_name}!` : 
            `Welcome, ${currentUser.username}!`;
        
        welcomeName.textContent = displayName;
        welcomeContainer.style.display = 'flex';
    }
}

async function logout() {
    if (currentUserType === 'admin') {
        await logoutAdmin();
    }

    currentUserType = null;
    currentUser = null;
    sessionToken = null;
    clearPersistedAuthState();

    showEntrySelection();
}

function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.add('show');
    }
}

function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.remove('show');
    }
}

// Initialize the main application
async function initializeApp() {
    /* @tweakable app initialization configuration */
    const enableInitDebug = true;
    const initTimeout = 10000;
    
    try {
        if (enableInitDebug) {
            console.log('START Initializing main application...');
        }
        
        // Load initial data
        await loadEmployeeList();
        await loadLeaveApplications();
        await loadEmployeeSummary();
        await loadHolidays();

        // Set up form handlers and other functionality
        setupEmployeeManagement();
        setupHolidayManagement();
        setupLeaveApplication();
        setupDateCalculation();
        setupLeaveTypeHandling();
        
        if (enableInitDebug) {
            console.log('SUCCESS Application initialization completed');
        }
        
    } catch (error) {
        console.error('ERROR Application initialization failed:', error);
    }
}

// Employee management functions
async function handleEmployeeFormSubmit() {
    /* @tweakable employee form submission debugging */
    const debugEmployeeSubmission = true;
    
    if (debugEmployeeSubmission) {
        console.log('INFO Employee form submitted');
    }
    
    const form = document.getElementById('employeeForm');
    const formData = new FormData(form);
    
    const employeeData = {
        first_name: formData.get('firstName'),
        surname: formData.get('surname'),
        personal_email: formData.get('personalEmail'),
        annual_leave: parseInt(formData.get('annualLeave')) || 15,
        sick_leave: parseInt(formData.get('sickLeave')) || 5
    };
    
    try {
        if (showEmployeeCreationFeedback) {
            showLoading();
        }
        
        if (debugEmployeeSubmission) {
            console.log('INFO Creating employee record...', employeeData);
        }
        
        const newEmployee = await room.collection('employee').create(employeeData);
        
        if (debugEmployeeSubmission) {
            console.log('SUCCESS Employee created:', newEmployee);
        }
        
        // Reset form
        form.reset();
        updatePrivilegeLeave('serviceLength', 'annualLeave');
        
        // Reload employee table
        await loadEmployeeList();
        
        alert(`Employee ${employeeData.first_name} ${employeeData.surname} added successfully!`);
        
    } catch (error) {
        console.error('ERROR Error adding employee:', error);
        alert(`Error adding employee: ${error.message}`);
    } finally {
        if (showEmployeeCreationFeedback) {
            hideLoading();
        }
    }
}

async function loadEmployeeList() {
    try {
        // Fetch employees and all leave balance records in parallel
        const [employees, balances] = await Promise.all([
            room.collection('employee').getList(),
            room.collection('leave_balance').getList()
        ]);

        // Merge balance information with each employee
        const mergedEmployees = employees.map(emp => {
            const empBalances = balances.filter(b => b.employee_id === emp.id);
            const privilege = empBalances.find(b => b.balance_type === 'PRIVILEGE');
            const sick = empBalances.find(b => b.balance_type === 'SICK');
            return {
                ...emp,
                privilege_remaining: privilege ? privilege.remaining_days : 0,
                sick_remaining: sick ? sick.remaining_days : 0
            };
        });

        loadEmployeeTable(mergedEmployees);
        populateEmployeeDropdown(employees);
    } catch (error) {
        console.error('Error loading employees:', error);
    }
}

function loadEmployeeTable(employees) {
    const tbody = document.getElementById('employeeTableBody');
    tbody.innerHTML = '';

    employees.forEach(employee => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${employee.first_name} ${employee.surname}</td>
            <td>${employee.personal_email}</td>
            <td>${employee.privilege_remaining}</td>
            <td>${employee.sick_remaining}</td>
            <td class="action-buttons">
                <button class="btn btn-secondary" onclick="editEmployee('${employee.id}')">Edit</button>
                <button class="btn btn-danger" onclick="deleteEmployee('${employee.id}')">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function populateEmployeeDropdown(employees) {
    // This would populate a dropdown if we had one
    console.log(`Employee dropdown would be populated with ${employees.length} employees`);
}

function setupEmployeeManagement() {
    /* @tweakable whether to enable employee management setup debugging */
    const debugEmployeeSetup = true;
    
    if (debugEmployeeSetup) {
        console.log('INFO Setting up employee management handlers...');
    }
    
    // Note: Form handler is already set up in setupCriticalFormHandlers
    // This function can handle additional employee management setup
    
    if (debugEmployeeSetup) {
        console.log('SUCCESS Employee management setup completed');
    }
}

function setupHolidayManagement() {
    /* @tweakable whether to enable holiday management setup debugging */
    const debugHolidaySetup = true;

    if (debugHolidaySetup) {
        console.log('INFO Setting up holiday management handlers...');
    }

    // Only attach handlers once
    if (holidayFormInitialized) {
        if (debugHolidaySetup) {
            console.log('INFO Holiday form handlers already initialized');
        }
        return;
    }

    const populateBtn = document.getElementById('populateHolidaysBtn');
    if (populateBtn) {
        populateBtn.addEventListener('click', async () => {
            const confirmPopulate = confirm('Auto-populate holidays for the next fiscal year? This will replace existing holidays.');
            if (confirmPopulate) {
                await populateNextFiscalYearHolidays();
            }
        });

        if (debugHolidaySetup) {
            console.log('SUCCESS Populate holidays button handler attached');
        }
    }

    const holidayForm = document.getElementById('holidayForm');
    if (holidayForm) {
        holidayForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const date = document.getElementById('holidayDate').value;
            const name = document.getElementById('holidayName').value;

            try {
                await room.collection('holiday').create({ date, name });
                holidayForm.reset();
                await loadHolidays();
            } catch (error) {
                console.error('Error adding holiday:', error);
                alert('Failed to add holiday: ' + (error.message || 'Unknown error'));
            }
        });

        if (debugHolidaySetup) {
            console.log('SUCCESS Holiday form submit handler attached');
        }
    }

    holidayFormInitialized = true;

    if (debugHolidaySetup) {
        console.log('SUCCESS Holiday management setup completed');
    }
}

function setupLeaveApplication() {
    console.log('INFO Setting up leave application handlers...');
}

function setupDateCalculation() {
    /* @tweakable whether to enable automatic date calculation */
    const enableAutoCalculation = true;

    const startDate = document.getElementById('startDate');
    const endDate = document.getElementById('endDate');
    const startTime = document.getElementById('startTime');
    const endTime = document.getElementById('endTime');

    if (startDate && endDate && startTime && endTime && enableAutoCalculation) {
        [startDate, endDate, startTime, endTime].forEach(field =>
            field.addEventListener('change', calculateLeaveDuration)
        );
    }
}

const EARLIEST_LEAVE_MINUTES = 6 * 60 + 30;
const LATEST_LEAVE_MINUTES = 15 * 60;
const TIME_WINDOW_ERROR_CODES = {
    START_OUTSIDE_WORKING_HOURS: 'START_OUTSIDE_WORKING_HOURS',
    END_OUTSIDE_WORKING_HOURS: 'END_OUTSIDE_WORKING_HOURS',
};

function parseTimeToMinutes(timeValue) {
    if (!timeValue || typeof timeValue !== 'string') {
        return null;
    }

    const [hoursPart, minutesPart] = timeValue.split(':');
    if (hoursPart == null || minutesPart == null) {
        return null;
    }

    const hours = Number.parseInt(hoursPart, 10);
    const minutes = Number.parseInt(minutesPart, 10);

    if (!Number.isInteger(hours) || !Number.isInteger(minutes)) {
        return null;
    }

    if (minutes < 0 || minutes >= 60 || hours < 0 || hours > 23) {
        return null;
    }

    return hours * 60 + minutes;
}

function showTimeWarningModal(message) {
    const modal = document.getElementById('timeWarningModal');
    const messageElement = document.getElementById('timeWarningMessage');

    if (!modal) {
        return;
    }

    if (messageElement && typeof message === 'string' && message.trim().length > 0) {
        messageElement.textContent = message;
    }

    modal.classList.add('show');
}

function closeTimeWarningModal() {
    const modal = document.getElementById('timeWarningModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

function showTimeWarningIfNeeded(validation) {
    if (!validation || validation.valid) {
        return;
    }

    if (
        validation.code === TIME_WINDOW_ERROR_CODES.START_OUTSIDE_WORKING_HOURS ||
        validation.code === TIME_WINDOW_ERROR_CODES.END_OUTSIDE_WORKING_HOURS
    ) {
        const message = validation.message || 'Selected times must fall within working hours (06:30–15:00).';
        showTimeWarningModal(message);
    }
}

function validateSingleDayTimeWindow(startDate, endDate, startTime, endTime) {
    if (!startDate || !endDate || startDate !== endDate) {
        return { valid: true, code: null };
    }

    const startMinutes = parseTimeToMinutes(startTime);
    const endMinutes = parseTimeToMinutes(endTime);

    if (startMinutes == null || endMinutes == null) {
        return {
            valid: false,
            code: 'INVALID_TIME_FORMAT',
            message: 'Enter a valid start and end time in HH:MM format.',
        };
    }

    if (startMinutes < EARLIEST_LEAVE_MINUTES || startMinutes > LATEST_LEAVE_MINUTES) {
        return {
            valid: false,
            code: TIME_WINDOW_ERROR_CODES.START_OUTSIDE_WORKING_HOURS,
            message: 'Start time must fall within working hours (06:30–15:00).',
        };
    }

    if (endMinutes < EARLIEST_LEAVE_MINUTES || endMinutes > LATEST_LEAVE_MINUTES) {
        return {
            valid: false,
            code: TIME_WINDOW_ERROR_CODES.END_OUTSIDE_WORKING_HOURS,
            message: 'End time must fall within working hours (06:30–15:00).',
        };
    }

    if (endMinutes <= startMinutes) {
        return {
            valid: false,
            code: 'END_BEFORE_START',
            message: 'End time must be after the start time.',
        };
    }

    return {
        valid: true,
        code: null,
        startMinutes,
        endMinutes,
    };
}

function calculateLeaveDuration() {
    const startDateInput = document.getElementById('startDate');
    const endDateInput = document.getElementById('endDate');
    const startTimeInput = document.getElementById('startTime');
    const endTimeInput = document.getElementById('endTime');
    const durationText = document.getElementById('durationText');

    if (!durationText) {
        return;
    }

    const startDate = startDateInput?.value;
    const endDate = endDateInput?.value;
    const isMultiDay = Boolean(startDate && endDate && startDate !== endDate);

    if (startTimeInput && endTimeInput) {
        startTimeInput.disabled = isMultiDay;
        endTimeInput.disabled = isMultiDay;
    }

    if (!startDate || !endDate) {
        durationText.textContent = 'Duration will be calculated automatically';
        return;
    }

    const rawStartTime = startTimeInput?.value || '';
    const rawEndTime = endTimeInput?.value || '';
    const defaultedStartTime = rawStartTime || DEFAULT_WORKDAY_START_TIME;
    const defaultedEndTime = rawEndTime || DEFAULT_WORKDAY_END_TIME;
    const startTime = isMultiDay ? defaultedStartTime : rawStartTime;
    const endTime = isMultiDay ? defaultedEndTime : rawEndTime;

    if (!isMultiDay && (!startTime || !endTime)) {
        durationText.textContent = 'Please select start and end times to calculate duration';
        return;
    }

    if (!isMultiDay && startTime && endTime) {
        const validation = validateSingleDayTimeWindow(startDate, endDate, startTime, endTime);
        showTimeWarningIfNeeded(validation);
        if (!validation.valid) {
            durationText.textContent = validation.message;
            return;
        }
    }

    const hours = calculateTotalHours(startDate, endDate, startTime, endTime);

    if (hours > 0) {
        const days = Math.round((hours / WORK_HOURS_PER_DAY) * 100) / 100;
        durationText.textContent = `Duration: ${hours.toFixed(2)} hour(s) (${days.toFixed(2)} day(s))`;
    } else {
        durationText.textContent = 'Duration will be calculated automatically';
    }
}

function setupLeaveTypeHandling() {
    const radios = document.querySelectorAll('input[name="leaveType"]');
    const reasonTextarea = document.getElementById('reason');
    const reasonNote = document.getElementById('reasonNote');

    radios.forEach(radio => {
        radio.addEventListener('change', function() {
            const anyChecked = Array.from(radios).some(rb => rb.checked);

            if (anyChecked) {
                reasonTextarea.disabled = false;
                reasonNote.textContent = 'Please provide details about your leave request.';
            } else {
                reasonTextarea.disabled = true;
                reasonNote.textContent = 'Please select a leave type above to enable this field, or select "Other" to specify a custom reason.';
            }
        });
    });
}

async function submitLeaveApplication(event, returnDate = null) {
    event.preventDefault();

    try {
        showLoading();

        const formData = new FormData(event.target);
        const selectedLeaveType = formData.get('leaveType');
        const startDate = formData.get('startDate');
        const endDate = formData.get('endDate');
        const startTime = formData.get('startTime');
        const endTime = formData.get('endTime');
        const startTimeInput = document.getElementById('startTime');
        const endTimeInput = document.getElementById('endTime');
        const isMultiDay = Boolean(startDate && endDate && startDate !== endDate);
        const durationText = document.getElementById('durationText');

        if (!isMultiDay) {
            if (!startTime || !endTime) {
                if (durationText) {
                    durationText.textContent = 'Please select start and end times before submitting your request.';
                }
                hideLoading();
                return;
            }

            const validation = validateSingleDayTimeWindow(startDate, endDate, startTime, endTime);
            showTimeWarningIfNeeded(validation);
            if (!validation.valid) {
                if (durationText) {
                    durationText.textContent = validation.message;
                }
                hideLoading();
                return;
            }
        }

        const defaultedStartTime = (startTimeInput?.value || '').trim() || DEFAULT_WORKDAY_START_TIME;
        const defaultedEndTime = (endTimeInput?.value || '').trim() || DEFAULT_WORKDAY_END_TIME;

        const effectiveStartTime = isMultiDay ? defaultedStartTime : (startTime || null);
        const effectiveEndTime = isMultiDay ? defaultedEndTime : (endTime || null);
        const totalHours = calculateTotalHours(
            startDate,
            endDate,
            effectiveStartTime,
            effectiveEndTime
        );
        const totalDays = totalHours > 0 ? Math.round((totalHours / WORK_HOURS_PER_DAY) * 10000) / 10000 : 0;

        if (!returnDate) {
            returnDate = determineReturnDate(endDate, totalHours);
        }

        const applicationData = {
            employee_id: currentUser.id,
            employee_name: `${currentUser.first_name} ${currentUser.surname}`,
            start_date: startDate,
            end_date: endDate,
            start_time: effectiveStartTime,
            end_time: effectiveEndTime,
            leave_type: selectedLeaveType,
            selected_reasons: selectedLeaveType ? [selectedLeaveType] : [],
            reason: formData.get('reason'),
            total_hours: totalHours,
            total_days: totalDays,
            status: 'Pending',
            return_date: returnDate
        };

        const result = await room.collection('leave_application').create(applicationData);

        // Show success modal
        document.getElementById('requestId').textContent = result.application_id || result.id;
        document.getElementById('successModal').classList.add('show');

        // Reset form
        event.target.reset();
        calculateLeaveDuration();
        await updateEmployeeInfo();
        
    } catch (error) {
        alert(`Error submitting leave request: ${error.message}`);
    } finally {
        hideLoading();
    }
}

function calculateTotalHours(startDate, endDate, startTime, endTime) {
    if (!startDate || !endDate) return 0;

    const startClock = startTime || '00:00';
    const endClock = endTime || '23:59';

    const start = new Date(`${startDate}T${startClock}`);
    const end = new Date(`${endDate}T${endClock}`);

    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) {
        return 0;
    }

    const startDay = new Date(start);
    startDay.setHours(0, 0, 0, 0);
    const endDay = new Date(end);
    endDay.setHours(0, 0, 0, 0);

    const msPerHour = 1000 * 60 * 60;
    let total = 0;
    const current = new Date(startDay);

    while (current <= endDay) {
        const iso = current.toISOString().split('T')[0];
        const day = current.getDay();
        const isWeekend = day === 0 || day === 6;
        const isHoliday = holidayDates.has(iso);

        if (!isWeekend && !isHoliday) {
            const isFirstDay = current.getTime() === startDay.getTime();
            const isLastDay = current.getTime() === endDay.getTime();
            let hoursForDay = WORK_HOURS_PER_DAY;

            if (isFirstDay && isLastDay) {
                hoursForDay = Math.max(0, (end.getTime() - start.getTime()) / msPerHour);
            } else if (isFirstDay) {
                const nextDayStart = new Date(current);
                nextDayStart.setDate(nextDayStart.getDate() + 1);
                hoursForDay = Math.max(0, (nextDayStart.getTime() - start.getTime()) / msPerHour);
            } else if (isLastDay) {
                const dayStart = new Date(current);
                hoursForDay = Math.max(0, (end.getTime() - dayStart.getTime()) / msPerHour);
            }

            total += Math.min(hoursForDay, WORK_HOURS_PER_DAY);
        }

        current.setDate(current.getDate() + 1);
        current.setHours(0, 0, 0, 0);
    }

    return Math.round(total * 100) / 100;
}

function getApplicationHours(app) {
    if (!app) return 0;
    if (typeof app.total_hours === 'number') {
        return app.total_hours;
    }
    if (app.total_hours) {
        const parsed = parseFloat(app.total_hours);
        if (!Number.isNaN(parsed)) {
            return parsed;
        }
    }
    if (app.total_days) {
        const days = parseFloat(app.total_days);
        if (!Number.isNaN(days)) {
            return days * WORK_HOURS_PER_DAY;
        }
    }
    if (app.start_date && app.end_date) {
        return calculateTotalHours(app.start_date, app.end_date, app.start_time, app.end_time);
    }
    return 0;
}

function formatDurationFromHours(hours) {
    const totalHours = Number.isFinite(hours) ? hours : parseFloat(hours) || 0;
    const roundedHours = Math.round(totalHours * 100) / 100;
    const days = Math.round((roundedHours / WORK_HOURS_PER_DAY) * 100) / 100;
    return `${roundedHours.toFixed(2)} h (${days.toFixed(2)} d)`;
}

function formatHours(hours) {
    const totalHours = Number.isFinite(hours) ? hours : parseFloat(hours) || 0;
    const roundedHours = Math.round(totalHours * 100) / 100;
    return `${roundedHours.toFixed(2)} h`;
}

function formatLeaveTypeLabel(leaveType) {
    if (leaveType == null) {
        return '';
    }

    const normalized = String(leaveType).trim();
    if (!normalized) {
        return '';
    }

    return normalized
        .split(/\s+/)
        .map(word =>
            word
                .split('-')
                .map(segment => {
                    if (!segment) {
                        return segment;
                    }
                    return segment.charAt(0).toUpperCase() + segment.slice(1);
                })
                .join('-')
        )
        .join(' ');
}

function getNextWorkday(dateStr) {
    if (!dateStr) return null;
    const date = new Date(dateStr + 'T00:00');
    date.setHours(0, 0, 0, 0);

    while (true) {
        date.setDate(date.getDate() + 1);
        const iso = date.toISOString().split('T')[0];
        const day = date.getDay();
        if (day !== 0 && day !== 6 && !holidayDates.has(iso)) {
            return iso;
        }
    }
}

function determineReturnDate(endDate, totalHours) {
    if (!endDate) {
        return '';
    }

    if (totalHours > 0 && totalHours < WORK_HOURS_PER_DAY) {
        return endDate;
    }

    return getNextWorkday(endDate) || endDate;
}

async function loadLeaveApplications() {
    try {
        const applications = await room.collection('leave_application').getList({ status: 'Pending' });

        const tbody = document.getElementById('applicationsTableBody');
        if (!tbody) {
            console.warn('applicationsTableBody element not found');
            return;
        }
        tbody.innerHTML = '';

        applications.forEach(app => {
            const row = document.createElement('tr');
            const leaveLabel = formatLeaveTypeLabel(app.leave_type);
            row.innerHTML = `
                <td>${app.application_id || app.id}</td>
                <td>${app.employee_name || app.employee_id}</td>
                <td>${leaveLabel}</td>
                <td>${app.start_date} ${app.start_time || ''}</td>
                <td>${app.end_date} ${app.end_time || ''}</td>
                <td>${formatDurationFromHours(getApplicationHours(app))}</td>
                <td class="application-actions">
                    <button class="btn btn-success approve-btn">Approve</button>
                    <button class="btn btn-danger reject-btn">Reject</button>
                </td>
            `;
            tbody.appendChild(row);

            const approveBtn = row.querySelector('.approve-btn');
            if (approveBtn) {
                approveBtn.addEventListener('click', () =>
                    updateApplicationStatus(app.id ?? app.application_id, 'Approved')
                );
            }
            const rejectBtn = row.querySelector('.reject-btn');
            if (rejectBtn) {
                rejectBtn.addEventListener('click', () =>
                    updateApplicationStatus(app.id ?? app.application_id, 'Rejected')
                );
            }
        });

        if (applications.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="7">No leave applications found</td>';
            tbody.appendChild(row);
        }

    } catch (error) {
        console.error('Error loading leave applications:', error);
    }
}

// Load summary of employee leave usage and balances
async function loadEmployeeSummary() {
    try {
        const [employees, balances, applications] = await Promise.all([
            room.collection('employee').getList(),
            room.collection('leave_balance').getList(),
            room.collection('leave_application').getList()
        ]);

        const searchInput = document.getElementById('employeeSearch');
        const filter = searchInput ? searchInput.value.trim().toLowerCase() : '';

        const summary = new Map();

        employees.forEach(emp => {
            const name = emp.first_name
                ? `${emp.first_name} ${emp.surname || ''}`.trim()
                : emp.employee_name || emp.username || emp.email || emp.id;
            summary.set(emp.id, {
                name,
                privilegeAllocated: 0,
                privilegeUsed: 0,
                privilegeRemaining: 0,
                sickAllocated: 0,
                sickUsed: 0,
                sickRemaining: 0
            });
        });

        balances.forEach(bal => {
            const info = summary.get(bal.employee_id);
            if (!info) return;
            const allocated = (parseFloat(bal.allocated_days) || 0) +
                (parseFloat(bal.carryforward_days) || 0);
            const remaining = parseFloat(bal.remaining_days) || 0;

            if (bal.balance_type === 'PRIVILEGE') {
                info.privilegeAllocated = allocated;
                info.privilegeRemaining = remaining;
            } else if (bal.balance_type === 'SICK') {
                info.sickAllocated = allocated;
                info.sickRemaining = remaining;
            }
        });

        applications.forEach(app => {
            const info = summary.get(app.employee_id);
            if (!info) return;

            const type = (app.leave_type || '').trim().toLowerCase();
            const hours = getApplicationHours(app);
            const days = hours / WORK_HOURS_PER_DAY;

            if (app.status === 'Pending') {
                return;
            }

            if (app.status === 'Approved') {
                const privilegeTypes = ['privilege', 'pl', 'vacation-annual', 'personal', 'cash-out'];
                const sickTypes = ['sick', 'sl'];

                if (privilegeTypes.includes(type)) {
                    info.privilegeUsed += days;
                } else if (sickTypes.includes(type)) {
                    info.sickUsed += days;
                }
            }
        });

        summary.forEach(info => {
            if (info.privilegeAllocated && info.privilegeRemaining == null) {
                info.privilegeRemaining = info.privilegeAllocated - info.privilegeUsed;
            }
            if (info.sickAllocated && info.sickRemaining == null) {
                info.sickRemaining = info.sickAllocated - info.sickUsed;
            }
        });

        const tbody = document.getElementById('employeeStatusTableBody');
        if (!tbody) {
            console.warn('employeeStatusTableBody element not found');
            return;
        }
        tbody.innerHTML = '';

        let hasRows = false;
        for (const info of summary.values()) {
            if (filter && !info.name.toLowerCase().includes(filter)) continue;
            const row = document.createElement('tr');
            const pClass = info.privilegeRemaining <= 0 ? "remaining-alert" : "";
            const sClass = info.sickRemaining <= 0 ? "remaining-alert" : "";
            row.innerHTML = `
                <td>${info.name}</td>
                <td>${info.privilegeAllocated}</td>
                <td>${info.privilegeUsed}</td>
                <td class="${pClass}">${info.privilegeRemaining}</td>
                <td>${info.sickAllocated}</td>
                <td>${info.sickUsed}</td>
                <td class="${sClass}">${info.sickRemaining}</td>
            `;
            tbody.appendChild(row);
            hasRows = true;
        }

        if (!hasRows) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="7">No employee data found</td>';
            tbody.appendChild(row);
        }
    } catch (error) {
        console.error('Error loading employee summary:', error);
    }
}

async function updateApplicationStatus(id, newStatus) {
    showLoading();

    // Ensure update modal is hidden before proceeding
    const updateModal = document.getElementById('updateSuccessModal');
    if (updateModal) {
        updateModal.classList.remove('show');
        document.getElementById('updateSuccessHeading').textContent = '';
        document.getElementById('updateStatusText').textContent = '';
        document.getElementById('updateRequestId').textContent = '';
    }

    // Disable all action buttons to prevent duplicate requests
    const actionButtons = document.querySelectorAll('.approve-btn, .reject-btn');
    actionButtons.forEach(btn => (btn.disabled = true));

    try {
        const result = await room.collection('leave_application').update(id, { status: newStatus });
        await loadLeaveApplications();
        await loadEmployeeSummary();
        await loadEmployeeList();

        const emailStatus = result?.email_status || {};
        if (emailStatus.admin && emailStatus.employee) {
            const heading = newStatus === 'Approved'
                ? '✅ Application Approved'
                : '❌ Application Rejected';
            document.getElementById('updateSuccessHeading').textContent = heading;
            document.getElementById('updateStatusText').textContent = newStatus;
            document.getElementById('updateRequestId').textContent = result.application_id || id;
            document.getElementById('updateSuccessModal').classList.add('show');
        } else {
            alert('Application updated but email notification failed');
        }
    } catch (error) {
        const requestUrl = `leave_application/${id}`;
        const status = error?.status ?? error?.response?.status;
        const statusText = error?.statusText ?? error?.response?.statusText;
        const responseBody = typeof error?.body === 'string' ? error.body : '';
        const responseData = error?.data;

        let backendMessage = '';
        if (responseData && typeof responseData === 'object') {
            backendMessage = responseData.message || responseData.error || responseData.detail || '';
        }
        if (!backendMessage && responseBody) {
            backendMessage = responseBody;
        }
        if (!backendMessage && error?.message) {
            backendMessage = error.message;
        }

        console.error('Error updating application status:', {
            requestUrl,
            status,
            statusText,
            responseBody,
            responseData,
            originalError: error,
        });

        let alertMessage = `Failed to update application status for ID ${id}.`;
        if (status) {
            alertMessage += ` Status: ${status}${statusText ? ` ${statusText}` : ''}.`;
        }
        if (backendMessage) {
            const normalizedBackendMessage = String(backendMessage).trim();
            if (normalizedBackendMessage) {
                alertMessage += ` Reason: ${normalizedBackendMessage}`;
                if (!/[.!?]$/.test(normalizedBackendMessage)) {
                    alertMessage += '.';
                }
            }
        }

        alert(alertMessage);
    } finally {
        actionButtons.forEach(btn => (btn.disabled = false));
        hideLoading();
    }
}


function buildUnpaidApplicationMap(balanceHistory = [], employeeId = null) {
    const unpaidMap = new Map();
    const allowedTypes = new Set(['PRIVILEGE', 'SICK']);
    const targetEmployeeId = employeeId != null ? String(employeeId) : null;

    balanceHistory.forEach(entry => {
        if (!entry) return;

        const entryEmployeeId = entry.employee_id != null ? String(entry.employee_id) : null;
        if (targetEmployeeId && entryEmployeeId && entryEmployeeId !== targetEmployeeId) {
            return;
        }

        const changeType = (entry.change_type || '').toUpperCase();
        const balanceType = (entry.balance_type || '').toUpperCase();
        const rawId = entry.application_id || entry.applicationId || entry.leave_application_id || entry.leaveApplicationId;

        if (!rawId || changeType !== 'DEDUCTION' || !allowedTypes.has(balanceType)) {
            return;
        }

        const changeAmountRaw = entry.change_amount ?? entry.changeAmount;
        const previousBalanceRaw = entry.previous_balance ?? entry.previousBalance;

        const changeAmount = Number.parseFloat(changeAmountRaw);
        if (!Number.isFinite(changeAmount) || Math.abs(changeAmount) === 0) {
            return;
        }

        const requestedDays = Math.abs(changeAmount);
        const previousBalance = Number.parseFloat(previousBalanceRaw);
        const availableDays = Number.isFinite(previousBalance) ? Math.max(previousBalance, 0) : 0;

        const paidDays = Math.min(requestedDays, availableDays);
        const unpaidDays = Math.max(0, requestedDays - paidDays);

        const paidHours = Math.round(paidDays * WORK_HOURS_PER_DAY * 100) / 100;
        const unpaidHours = Math.round(unpaidDays * WORK_HOURS_PER_DAY * 100) / 100;

        const normalizedId = String(rawId);
        const existing = unpaidMap.get(normalizedId) || { paidHours: 0, unpaidHours: 0 };

        existing.paidHours += paidHours;
        existing.unpaidHours += unpaidHours;

        unpaidMap.set(normalizedId, existing);
    });

    return unpaidMap;
}

async function loadLeaveHistory(employeeId, status = null) {
    try {
        const statusParam = status ? `&status=${encodeURIComponent(status)}` : '';
        const [apps, balanceHistory] = await Promise.all([
            room
                .collection('leave_application')
                .makeRequest(
                    'GET',
                    `?employee_id=${encodeURIComponent(employeeId)}${statusParam}`
                ),
            room
                .collection('leave_balance_history')
                .makeRequest('GET')
        ]);

        const unpaidApplicationMap = buildUnpaidApplicationMap(balanceHistory, employeeId);

        const tbody = document.getElementById('employeeHistoryTableBody');
        tbody.innerHTML = '';

        apps.forEach(app => {
            const primaryKey = app?.id != null ? String(app.id) : null;
            const fallbackKey = app?.application_id != null ? String(app.application_id) : null;
            const displayId = app?.application_id != null ? app.application_id : (primaryKey || '');
            const totalHours = getApplicationHours(app);

            let historyInfo = null;
            if (primaryKey && unpaidApplicationMap.has(primaryKey)) {
                historyInfo = unpaidApplicationMap.get(primaryKey);
            } else if (fallbackKey && unpaidApplicationMap.has(fallbackKey)) {
                historyInfo = unpaidApplicationMap.get(fallbackKey);
            }
            let paidHours = totalHours;
            let unpaidHours = 0;

            if (historyInfo) {
                if (Number.isFinite(historyInfo.paidHours)) {
                    paidHours = historyInfo.paidHours;
                }
                if (Number.isFinite(historyInfo.unpaidHours)) {
                    unpaidHours = historyInfo.unpaidHours;
                }
                if (paidHours === 0 && unpaidHours === 0 && totalHours) {
                    paidHours = totalHours;
                }
            }

            const rawLeaveType = app.leave_type ?? '';
            const leaveTypeValue = rawLeaveType != null ? rawLeaveType.toString().trim() : '';
            const normalizedLeaveType = leaveTypeValue
                .toLowerCase()
                .replace(/[-\s]+/g, ' ')
                .trim();
            if (normalizedLeaveType === 'leave without pay' && Math.abs(unpaidHours) <= 0.01) {
                paidHours = 0;
                unpaidHours = Number.isFinite(totalHours) ? totalHours : 0;
            }
            const isCashOut = normalizedLeaveType === 'cash out' || normalizedLeaveType === 'cashout';

            const hasUnpaid = Math.abs(unpaidHours) > 0.01;
            const hasPaidHours = Math.abs(paidHours) > 0.01;
            const formattedLeaveType = formatLeaveTypeLabel(leaveTypeValue || rawLeaveType);
            const leaveLabel = hasUnpaid ? 'Unpaid Leave' : formattedLeaveType;
            const paidHoursStyleAttr = isCashOut
                ? ' style="color: #2e7d32; font-weight: 600;"'
                : (hasPaidHours ? ' style="color: #1565c0; font-weight: 600;"' : '');
            const unpaidHoursStyleAttr = hasUnpaid ? ' style="color: #c62828; font-weight: 600;"' : '';
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${displayId}</td>
                <td>${leaveLabel}</td>
                <td>${app.start_date} ${app.start_time || ''}</td>
                <td>${app.end_date} ${app.end_time || ''}</td>
                <td>${formatDurationFromHours(totalHours)}</td>
                <td${paidHoursStyleAttr}>${formatHours(paidHours)}</td>
                <td${unpaidHoursStyleAttr}>${formatHours(unpaidHours)}</td>
                <td><span class="status-badge status-${(app.status || '').toLowerCase()}">${app.status}</span></td>
            `;
            tbody.appendChild(row);
        });

        if (apps.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="8">No leave applications found</td>';
            tbody.appendChild(row);
        }
    } catch (error) {
        console.error('Error loading leave history:', error);
    }
}

function getFiscalYearRange(date = new Date()) {
    const fiscalStartMonth = 0; // January; change if fiscal year starts elsewhere
    const year = date.getMonth() >= fiscalStartMonth ? date.getFullYear() : date.getFullYear() - 1;
    const start = new Date(year, fiscalStartMonth, 1);
    const end = new Date(year + 1, fiscalStartMonth, 0);
    return { start, end };
}

async function loadAdminLeaveHistory(search = '') {
    const requestId = ++adminHistoryRequestId;
    const tbody = document.getElementById('adminHistoryTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    try {
        const [apps, balanceHistory] = await Promise.all([
            room.collection('leave_application').getList({ status: 'Approved' }),
            room.collection('leave_balance_history').getList()
        ]);
        if (requestId !== adminHistoryRequestId) return;

        const { start: fiscalStart, end: fiscalEnd } = getFiscalYearRange();

        const unpaidApplicationMap = buildUnpaidApplicationMap(balanceHistory);

        const filtered = apps.filter(app => {
            const name = (app.employee_name || '').toLowerCase();
            const nameMatch = name.includes(search.toLowerCase());
            const appStart = new Date(app.start_date);
            const appEnd = new Date(app.end_date);
            const inFiscalYear = appStart >= fiscalStart && appEnd <= fiscalEnd;
            return nameMatch && inFiscalYear;
        });

        filtered.sort((a, b) => new Date(b.start_date) - new Date(a.start_date));

        filtered.forEach(app => {
            const primaryKey = app?.id != null ? String(app.id) : null;
            const fallbackKey = app?.application_id != null ? String(app.application_id) : null;
            const totalHours = getApplicationHours(app);

            let historyInfo = null;
            if (primaryKey && unpaidApplicationMap.has(primaryKey)) {
                historyInfo = unpaidApplicationMap.get(primaryKey);
            } else if (fallbackKey && unpaidApplicationMap.has(fallbackKey)) {
                historyInfo = unpaidApplicationMap.get(fallbackKey);
            }
            let paidHours = totalHours;
            let unpaidHours = 0;

            if (historyInfo) {
                if (Number.isFinite(historyInfo.paidHours)) {
                    paidHours = historyInfo.paidHours;
                }
                if (Number.isFinite(historyInfo.unpaidHours)) {
                    unpaidHours = historyInfo.unpaidHours;
                }
                if (paidHours === 0 && unpaidHours === 0 && totalHours) {
                    paidHours = totalHours;
                }
            }

            const rawLeaveType = app.leave_type ?? '';
            const leaveTypeValue = rawLeaveType != null ? rawLeaveType.toString().trim() : '';
            const normalizedLeaveType = leaveTypeValue
                .toLowerCase()
                .replace(/[-\s]+/g, ' ')
                .trim();
            if (normalizedLeaveType === 'leave without pay' && Math.abs(unpaidHours) <= 0.01) {
                paidHours = 0;
                unpaidHours = Number.isFinite(totalHours) ? totalHours : 0;
            }
            const isCashOut = normalizedLeaveType === 'cash out' || normalizedLeaveType === 'cashout';

            const hasUnpaid = Math.abs(unpaidHours) > 0.01;
            const hasPaidHours = Math.abs(paidHours) > 0.01;
            const formattedLeaveType = formatLeaveTypeLabel(leaveTypeValue || rawLeaveType);
            const leaveLabel = hasUnpaid ? 'Unpaid Leave' : formattedLeaveType;
            const paidHoursStyleAttr = isCashOut
                ? ' style="color: #2e7d32; font-weight: 600;"'
                : (hasPaidHours ? ' style="color: #1565c0; font-weight: 600;"' : '');
            const unpaidHoursClassAttr = hasUnpaid ? ' class="unpaid-hours"' : '';
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${app.employee_name}</td>
                <td>${leaveLabel}</td>
                <td>${app.start_date} ${app.start_time || ''} - ${app.end_date} ${app.end_time || ''}</td>
                <td>${formatDurationFromHours(totalHours)}</td>
                <td${paidHoursStyleAttr}>${formatHours(paidHours)}</td>
                <td${unpaidHoursClassAttr}>${formatHours(unpaidHours)}</td>
            `;
            tbody.appendChild(tr);
        });

        if (filtered.length === 0) {
            const tr = document.createElement('tr');
            tr.innerHTML = '<td colspan="6">No leave applications found</td>';
            tbody.appendChild(tr);
        }
    } catch (error) {
        console.error('Error loading admin leave history:', error);
    }
}

async function exportAdminHistoryPdf() {
    const container = document.getElementById('adminHistoryTable');
    if (!container) return;

    const dateCells = container.querySelectorAll('tbody tr td:nth-child(3)');
    let earliest = null;
    let latest = null;
    dateCells.forEach(cell => {
        const [startStr, endStr] = cell.textContent.split(' - ');
        const start = new Date(startStr.trim());
        const end = new Date(endStr.trim());
        if (!earliest || start < earliest) earliest = start;
        if (!latest || end > latest) latest = end;
    });

    const format = d => `${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getFullYear()).slice(-2)}`;
    const range = earliest && latest ? `${format(earliest)}-${format(latest)}` : '';

    const nameInput = document.getElementById('historySearch');
    let name = nameInput ? nameInput.value.trim() : '';
    let namePart = 'AllEmployees';
    if (name) {
        const parts = name.split(/\s+/);
        const first = parts[0] || '';
        const last = parts.length > 1 ? parts[parts.length - 1] : '';
        namePart = (last + first).replace(/\s+/g, '') || 'AllEmployees';
    }

    const filename = `LeaveHistory_${namePart}_${range}.pdf`;

    if (typeof html2pdf !== 'undefined') {
        await html2pdf().from(container).save(filename);
    }
}

async function loadHolidays() {
    try {
        const tbody = document.getElementById('holidayTableBody');
        if (tbody) {
            tbody.innerHTML = '';
        }

        const holidays = await room.collection('holiday').getList();

        // Populate global holiday date cache
        holidayDates.clear();
        for (const h of holidays) {
            if (h.date) {
                holidayDates.add(h.date);
            }
        }

        if (tbody) {
            if (holidays.length === 0) {
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="3">No holidays found</td>';
                tbody.appendChild(row);
            } else {
                holidays.sort((a, b) => new Date(a.date) - new Date(b.date));
                for (const holiday of holidays) {
                    const row = document.createElement('tr');
                    const dateCell = document.createElement('td');
                    dateCell.textContent = holiday.date;
                    const nameCell = document.createElement('td');
                    nameCell.textContent = holiday.name;
                    const actionCell = document.createElement('td');
                    const delBtn = document.createElement('button');
                    delBtn.textContent = 'Delete';
                    delBtn.className = 'btn btn-danger';
                    delBtn.addEventListener('click', async () => {
                        if (confirm('Delete this holiday?')) {
                            await room.collection('holiday').delete(holiday.id);
                            await loadHolidays();
                        }
                    });
                    actionCell.appendChild(delBtn);
                    row.appendChild(dateCell);
                    row.appendChild(nameCell);
                    row.appendChild(actionCell);
                    tbody.appendChild(row);
                }
            }
        }
    } catch (error) {
        console.error('Error loading holidays:', error);
    }
}

function getLastWeekdayOfMonth(year, month, weekday) {
    const lastDay = new Date(year, month + 1, 0);
    const diff = (lastDay.getDay() - weekday + 7) % 7;
    return new Date(year, month, lastDay.getDate() - diff);
}

function getFirstWeekdayOfMonth(year, month, weekday) {
    const firstDay = new Date(year, month, 1);
    const diff = (weekday - firstDay.getDay() + 7) % 7;
    return new Date(year, month, 1 + diff);
}

function formatDate(date) {
    return date.toISOString().split('T')[0];
}

async function populateNextFiscalYearHolidays() {
    const year = new Date().getFullYear() + 1;
    const holidays = [
        { date: `${year}-01-01`, name: 'New Years Day' },
        { date: formatDate(getLastWeekdayOfMonth(year, 4, 1)), name: 'Memorial Day' },
        { date: `${year}-07-04`, name: 'Independence Day' },
        { date: formatDate(getFirstWeekdayOfMonth(year, 8, 1)), name: 'Labor Day' },
        { date: formatDate(getLastWeekdayOfMonth(year, 10, 4)), name: 'Thanksgiving Day' },
        { date: `${year}-12-25`, name: 'Christmas Day' }
    ];

    try {
        await fetch('/api/holiday/auto_populate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ holidays })
        });
        await loadHolidays();
    } catch (error) {
        console.error('Error populating holidays:', error);
        alert('Failed to auto-populate holidays');
    }
}

function switchTab(tabName) {
    /* @tweakable whether to log tab switching for debugging */
    const logTabSwitching = true;

    if (logTabSwitching) {
        console.log(`INFO Switching to tab: ${tabName}`);
    }

    // Map hyphenated tab names to their camel-cased button IDs
    const tabButtonIds = {
        'leave-request': 'tabLeaveRequest',
        'check-history': 'tabCheckHistory',
        'employee-management': 'tabEmployeeManagement',
        'application-status': 'tabApplicationStatus',
        'holiday-dates': 'tabHolidayDates',
        'admin-history': 'tabAdminHistory'
    };
    
    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab content
    const targetTab = document.getElementById(tabName);
    if (targetTab) {
        targetTab.classList.add('active');
    }
    
    // Activate corresponding tab button
    const targetButtonId = tabButtonIds[tabName];
    if (targetButtonId) {
        const targetButton = document.getElementById(targetButtonId);
        if (targetButton) {
            targetButton.classList.add('active');
        }
    }

    // Load tab-specific data when needed
    if (tabName === 'check-history' && currentUser) {
        loadLeaveHistory(currentUser.id);
    } else if (tabName === 'application-status') {
        loadEmployeeSummary();
        loadLeaveApplications();
    } else if (tabName === 'admin-history') {
        const search = document.getElementById('historySearch')?.value || '';
        loadAdminLeaveHistory(search);
    }
}

// Utility functions
async function editEmployee(employeeId) {
    try {
        const employees = await room.collection('employee').getList();
        const employee = employees.find(e => e.id === employeeId);
        if (!employee) {
            alert('Employee not found');
            return;
        }

        const form = document.getElementById('editEmployeeForm');
        form.dataset.employeeId = employeeId;

        document.getElementById('editFirstName').value = employee.first_name || '';
        document.getElementById('editSurname').value = employee.surname || '';
        document.getElementById('editPersonalEmail').value = employee.personal_email || '';
        document.getElementById('editAnnualLeave').value = employee.annual_leave || 0;
        document.getElementById('editSickLeave').value = employee.sick_leave || 0;

        const serviceSelect = document.getElementById('editServiceLength');
        if (serviceSelect) {
            let lengthValue = '8+';
            if (employee.annual_leave === 5) {
                lengthValue = '1-3';
            } else if (employee.annual_leave === 10) {
                lengthValue = '4-7';
            }
            serviceSelect.value = lengthValue;
        }

        const balances = await LeaveBalanceAPI.getEmployeeBalances(employeeId);
        const priv = balances.find(b => b.balance_type === 'PRIVILEGE');
        const sick = balances.find(b => b.balance_type === 'SICK');
        document.getElementById('editRemainingPrivilege').value = priv ? priv.remaining_days : 0;
        document.getElementById('editRemainingSick').value = sick ? sick.remaining_days : 0;

        document.getElementById('editModal').classList.add('show');
    } catch (error) {
        console.error('Error editing employee:', error);
        alert(`Error editing employee: ${error.message}`);
    }
}

async function deleteEmployee(employeeId) {
    if (confirm('Are you sure you want to delete this employee?')) {
        try {
            await room.collection('employee').delete(employeeId);
            await loadEmployeeList();
            alert('Employee deleted successfully');
        } catch (error) {
            alert(`Error deleting employee: ${error.message}`);
        }
    }
}

async function resetAllLeaveBalances() {
    if (confirm('Are you sure you want to reset all leave balances? This action cannot be undone.')) {
        try {
            const resp = await fetch('/api/reset_balances', {
                method: 'POST',
                credentials: 'include'
            });
            if (!resp.ok) throw new Error('Request failed');
            await loadEmployeeList();
            await loadEmployeeSummary();
            alert('All leave balances reset successfully');
        } catch (error) {
            alert(`Error resetting leave balances: ${error.message}`);
        }
    }
}

// Modal functions
function closeErrorModal() {
    document.getElementById('errorModal').classList.remove('show');
}

function closeEditModal() {
    document.getElementById('editModal').classList.remove('show');
}

// Close success modal
document.addEventListener('DOMContentLoaded', function() {
    const closeModalBtn = document.getElementById('closeModal');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', function() {
            document.getElementById('successModal').classList.remove('show');
        });
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const updateCloseModalBtn = document.getElementById('updateCloseModal');
    if (updateCloseModalBtn) {
        updateCloseModalBtn.addEventListener('click', function() {
            const modal = document.getElementById('updateSuccessModal');
            modal.classList.remove('show');
            document.getElementById('updateSuccessHeading').textContent = '';
            document.getElementById('updateStatusText').textContent = '';
            document.getElementById('updateRequestId').textContent = '';
        });
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('employeeSearch');
    if (searchInput) {
        searchInput.addEventListener('input', loadEmployeeSummary);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('historySearch');
    const exportBtn = document.getElementById('historyExportBtn');

    let reloadTimeout;
    const reload = () => {
        clearTimeout(reloadTimeout);
        reloadTimeout = setTimeout(() => {
            const search = searchInput?.value || '';
            loadAdminLeaveHistory(search);
        }, 300);
    };

    if (searchInput) searchInput.addEventListener('input', reload);
    if (exportBtn) exportBtn.addEventListener('click', exportAdminHistoryPdf);
});

// Expose functions for debugging
window.showEmployeeLogin = showEmployeeLogin;
window.showAdminLogin = showAdminLogin;
window.switchTab = switchTab;
window.editEmployee = editEmployee;
window.deleteEmployee = deleteEmployee;
window.resetAllLeaveBalances = resetAllLeaveBalances;
window.closeErrorModal = closeErrorModal;
window.closeEditModal = closeEditModal;
window.closeTimeWarningModal = closeTimeWarningModal;
window.updateApplicationStatus = updateApplicationStatus;
window.loadEmployeeSummary = loadEmployeeSummary;
