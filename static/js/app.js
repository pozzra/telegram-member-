// Telegram Member Adder Web - Client Logic

const ADMIN_USERNAME = "kun_amra";
const BOT_USERNAME = "tg_adder_ativations_key_bot";

// Automatically resolve backend API server URL
// - If on port 5500 (Live Server), 3000, 5173, etc. or file:// => point to FastAPI on http://127.0.0.1:8000
// - If already on port 8000 or on production domain (e.g. Vercel) => use relative path ""
function computeApiBase() {
    const hostname = window.location.hostname;
    // Production cloud deployment (e.g. *.vercel.app, *.render.com)
    if (hostname && hostname !== "127.0.0.1" && hostname !== "localhost") {
        return "";
    }
    // Local development: file:// or any non-8000 port (e.g. Live Server on 5500)
    if (window.location.protocol === "file:" || !window.location.host || (window.location.port && window.location.port !== "8000")) {
        return "http://127.0.0.1:8000";
    }
    return "";
}
const API_BASE = computeApiBase();

let currentLanguage = localStorage.getItem("tgadder_lang") || "en";
let currentLicense = null;
let currentAccounts = [];
let websocket = null;
let isJobRunning = false;
let wsEverOpened = false; // Track whether the WS ever connected (avoid endless retry on serverless)

// ==========================================
// Machine ID (Device Fingerprint)
// ==========================================
function generateMachineId() {
    const stored = localStorage.getItem("tgadder_machine_id");
    if (stored) return stored;

    const nav = window.navigator;
    const screen = window.screen;
    const raw = [
        nav.userAgent,
        nav.language,
        screen.colorDepth,
        screen.width + "x" + screen.height,
        new Date().getTimezoneOffset(),
        nav.hardwareConcurrency || 0,
        nav.platform || "",
        location.hostname,
    ].join("|");

    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
        hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
    }
    const hex = (hash >>> 0).toString(16).toUpperCase().padStart(8, "0");
    const salt = Math.random().toString(36).substring(2, 8).toUpperCase();

    const mid = `MID-${hex}-${salt}`;
    localStorage.setItem("tgadder_machine_id", mid);
    return mid;
}

function getMachineId() {
    return generateMachineId();
}

function renderMachineId() {
    const el = document.getElementById("machineIdDisplay");
    if (el) el.innerText = getMachineId();
}

async function copyMachineId() {
    const mid = getMachineId();
    try {
        await navigator.clipboard.writeText(mid);
    } catch (e) {
        const el = document.getElementById("machineIdDisplay");
        if (el) {
            const range = document.createRange();
            range.selectNode(el);
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
            document.execCommand("copy");
            window.getSelection().removeAllRanges();
        }
    }
    const btn = document.getElementById("btnCopyMachineId");
    if (btn) {
        btn.innerHTML = '<i class="fas fa-check text-xs text-emerald-400"></i>';
        setTimeout(() => { btn.innerHTML = '<i class="fas fa-copy text-xs"></i>'; }, 1800);
    }
    logConsole(`Machine ID copied: ${mid}`, "info");
}

function requestKeyFromAdmin() {
    const mid = getMachineId();
    // Copy to clipboard
    navigator.clipboard.writeText(mid).catch(() => {});
    
    // Open Telegram Activation Bot with pre-filled Machine ID payload
    const safeMid = mid.replace(/-/g, "_");
    const botUrl = `https://t.me/${BOT_USERNAME}?start=${safeMid}`;
    window.open(botUrl, "_blank");
    logConsole(`Opened @${BOT_USERNAME} with your Machine ID. Click Start in Telegram!`, "success");
}

// ==========================================
// Bilingual translations
// ==========================================
const I18N = {
    en: {
        headerSubtitle: "Multi-Account Load Balancing & Member Inviter",
        licenseRequired: "License Required",
        licenseActive: "Active License",
        txtBannerLock: "License activation is required to add accounts and use Telegram Adder tools.",
        txtBannerBtn: "Activate License Key",
        titleAccounts: "Connected Accounts",
        btnAddAccount: "Add Account",
        btnSelectAll: "Select All",
        btnDeselectAll: "Deselect All",
        btnClearAll: "Clear All",
        rotationHint: "Accounts will automatically rotate per invite to share the workload without collisions.",
        titleScraper: "Scrape Source Group",
        descScraper: "Fetch usernames or IDs from a public or joined group",
        btnFetchText: "Fetch Members",
        titleMemberList: "Candidate Member List",
        btnUploadTxt: "Upload TXT",
        textareaHint: "Paste usernames, phone numbers, or IDs (one per line).",
        btnGenPhones: "Generate Random Phone Numbers",
        titleTarget: "Target Group & Adder Engine",
        descTarget: "Set your destination group and invite parameters",
        lblTargetGroup: "Target Group Link / Username",
        lblDelay: "Invite Delay:",
        lblMaxAcc: "Max per standard account:",
        btnStartText: "START ADDING MEMBERS",
        btnStopText: "STOP",
        modalLicTitle: "Tool Activation & License",
        modalLicDesc: "Enter your license key to unlock Telegram account login and adding tools.",
        lblEnterKey: "License Key",
        txtRequestAdminBtn: `Copy ID & Request License from Admin @${ADMIN_USERNAME}`,
        txtMachineIdHint: "Your Machine ID identifies your device. Send it to admin to receive your personal license key.",
        titleStep1: "Add Telegram Account",
        descStep1: "Enter your API credentials from my.telegram.org",
        btnGetHashText: "Get API Hash (my.telegram.org)",
        btnAutoFillHashText: "Auto-Fill Hash",
        lblGetHashLink: "Get Hash",
        btnSendCodeText: "Request Login Code",
        titleStep2: "Enter Login Code",
        lblOtpCode: "Confirmation Code (OTP)",
        lbl2FaPassword: "Two-Step Verification (2FA) Password",
        hint2FaPassword: "This account is protected with a Two-Step Verification (2FA) password.",
        btnToggle2Fa: "Account has 2FA? Click to enter password",
        btnBackStep1: "Back",
        btnSubmitOtpText: "Confirm Account",
        txtTabQr: "Scan QR Code",
        txtTabPhone: "Phone Number + Code",
        txtGeneratingQr: "Connecting to Telegram to generate QR Code...",
        txtScanInstruction: "Telegram > Settings > Devices > Link Desktop Device",
        txtScanSub: "Scan this QR code, or click the button below to confirm directly",
        txtOpenTgBtn: "Open Telegram App to Confirm",
        txtOpenTgApp: "👉 Open & Confirm in Telegram Directly",
        txtOpenTgAppHint: "Using phone? Tap button above to open Telegram app directly — no scanning needed!",
        txtQrStatusMsg: "Waiting for confirmation in Telegram...",
        txtRefreshQr: "Refresh QR Code",
        emptyAccounts: "No Telegram accounts connected yet.<br>Click '+ Add Account' to connect your first session."
    },
    km: {
        headerSubtitle: "ប្រព័ន្ធបន្ថែមសមាជិក Telegram ចែកគ្នាធ្វើការដោយស្វ័យប្រវត្តិ",
        licenseRequired: "ត្រូវការបញ្ចូល License Key",
        licenseActive: "License សកម្ម",
        txtBannerLock: "សូមធ្វើការ Activate License Key ជាមុនសិន ទើបអាចបន្ថែមគណនី និងប្រើប្រាស់ឧបករណ៍បាន។",
        txtBannerBtn: "បញ្ចូល License Key",
        titleAccounts: "គណនី Telegram ដែលបានភ្ជាប់",
        btnAddAccount: "បន្ថែមគណនី",
        btnSelectAll: "ជ្រើសរើសទាំងអស់",
        btnDeselectAll: "ដោះការជ្រើសរើស",
        btnClearAll: "លុបទាំងអស់",
        rotationHint: "គណនីទាំងអស់នឹងប្តូរវេនគ្នាបន្ថែមសមាជិកម្តងមួយៗដោយស្វ័យប្រវត្តិ មិនជាន់គ្នាឡើយ (ចែកគ្នាធ្វើការ)។",
        titleScraper: "ទាញយកសមាជិកពីក្រុមប្រភព",
        descScraper: "ទាញយក Username ឬ ID ពីក្រុមសាធារណៈ ឬក្រុមដែលបានចូលរួម",
        btnFetchText: "ទាញយកសមាជិក",
        titleMemberList: "បញ្ជីសមាជិកដែលត្រូវបន្ថែម",
        btnUploadTxt: "បញ្ចូលឯកសារ TXT",
        textareaHint: "ដាក់ Username, លេខទូរស័ព្ទ ឬ ID (មួយជួរមួយ)",
        btnGenPhones: "បង្កើតលេខទូរស័ព្ទចៃដន្យ",
        titleTarget: "ក្រុមគោលដៅ និងម៉ាស៊ីនបន្ថែមសមាជិក",
        descTarget: "កំណត់ក្រុមដែលចង់បន្ថែមសមាជិកចូល និងល្បឿន",
        lblTargetGroup: "តំណភ្ជាប់ក្រុមគោលដៅ (Target Group)",
        lblDelay: "រយៈពេលរង់ចាំ (វិនាទី):",
        lblMaxAcc: "ចំនួនកំណត់ក្នុងមួយគណនីធម្មតា:",
        btnStartText: "ចាប់ផ្តើមបន្ថែមសមាជិក",
        btnStopText: "បញ្ឈប់",
        modalLicTitle: "ការធ្វើឱ្យឧបករណ៍សកម្ម (License Key)",
        modalLicDesc: "បញ្ចូល License Key ដើម្បីបើកដំណើរការបន្ថែមគណនី និងឧបករណ៍។",
        lblEnterKey: "លេខកូដ License Key",
        txtRequestAdminBtn: `ចម្លង ID និងស្នើ License ពី Admin @${ADMIN_USERNAME}`,
        txtMachineIdHint: "Machine ID កំណត់អត្ថសញ្ញាណឧបករណ៍របស់អ្នក។ ផ្ញើវាទៅ Admin ដើម្បីទទួល License Key ផ្ទាល់ខ្លួន។",
        titleStep1: "បន្ថែមគណនី Telegram ថ្មី",
        descStep1: "បញ្ចូល API ID និង Hash ពី my.telegram.org",
        btnGetHashText: "យក API Hash (my.telegram.org)",
        btnAutoFillHashText: "បំពេញ Hash ស្វ័យប្រវត្តិ",
        lblGetHashLink: "យក Hash",
        btnSendCodeText: "ស្នើសុំកូដចូល Telegram",
        titleStep2: "បញ្ចូលលេខកូដសម្ងាត់ Login",
        lblOtpCode: "លេខកូដបញ្ជាក់ (OTP)",
        lbl2FaPassword: "លេខកូដសម្ងាត់ Two-Step Verification (2FA)",
        hint2FaPassword: "គណនីនេះត្រូវបានការពារដោយលេខកូដសម្ងាត់ 2FA (Two-Step Verification) ក្នុង Telegram។",
        btnToggle2Fa: "គណនីមាន 2FA? ចុចទីនេះដើម្បីបញ្ចូល Password",
        btnBackStep1: "ត្រឡប់ក្រោយ",
        btnSubmitOtpText: "បញ្ជាក់គណនី",
        txtTabQr: "ស្កេន QR Code",
        txtTabPhone: "តាមលេខទូរស័ព្ទ + កូដ",
        txtGeneratingQr: "កំពុងភ្ជាប់ទៅ Telegram ដើម្បីបង្កើត QR Code...",
        txtScanInstruction: "Telegram > ការកំណត់ > ឧបករណ៍ > ភ្ជាប់ឧបករណ៍កុំព្យូទ័រ",
        txtScanSub: "ស្កេន QR Code នេះ ឬចុចប៊ូតុងខាងក្រោមដើម្បី Confirm ភ្លាមៗ",
        txtOpenTgBtn: "បើកកម្មវិធី Telegram ដើម្បី Confirm",
        txtOpenTgApp: "👉 ចុចទីនេះដើម្បី Login ក្នុង Telegram ផ្ទាល់ (សម្រាប់ទូរស័ព្ទ)",
        txtOpenTgAppHint: "បើអ្នកកំពុងប្រើទូរស័ព្ទ ចុចប៊ូតុងខាងលើ Telegram នឹងបើកភ្លាមៗដើម្បីបញ្ជាក់ការ Login!",
        txtQrStatusMsg: "កំពុងរង់ចាំអ្នកចុច Confirm លើ Telegram...",
        txtRefreshQr: "បង្កើត QR Code ថ្មី",
        emptyAccounts: "មិនទាន់មានគណនី Telegram ណាត្រូវបានភ្ជាប់នៅឡើយទេ។<br>សូមចុច '+ បន្ថែមគណនី' ដើម្បី Login។"
    }
};

// ==========================================
// Initialization
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
    applyLanguage(currentLanguage);
    renderMachineId();
    if (getLicenseKey()) {
        loadAccountsFromLocalStorage();
    }
    initWebSocket();
    checkLicenseStatus();
    startSystemStatsPoller();

    const textarea = document.getElementById("memberListTextarea");
    if (textarea) textarea.addEventListener("input", updateCandidatesCount);
});

function getLicenseKey() {
    return localStorage.getItem("tgadder_license_key") || "";
}

function setLicenseKey(key) {
    if (key) {
        localStorage.setItem("tgadder_license_key", key.trim());
    } else {
        localStorage.removeItem("tgadder_license_key");
    }
}

function getAccountsStorageKey() {
    return "tgadder_accounts_" + getMachineId();
}

function loadAccountsFromLocalStorage() {
    try {
        const raw = localStorage.getItem(getAccountsStorageKey());
        if (raw) {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed) && parsed.length > 0) {
                currentAccounts = parsed;
                renderAccounts(currentAccounts);
                updateAccountsSummary();
                return true;
            }
        }
    } catch (e) {
        console.error("Error reading accounts from localStorage:", e);
    }
    return false;
}

function saveAccountsToLocalStorage(accounts) {
    try {
        if (Array.isArray(accounts)) {
            localStorage.setItem(getAccountsStorageKey(), JSON.stringify(accounts));
        }
    } catch (e) {
        console.error("Error saving accounts to localStorage:", e);
    }
}

function getAuthHeaders() {
    return {
        "Content-Type": "application/json",
        "X-License-Key": getLicenseKey(),
        "X-Machine-Id": getMachineId()
    };
}

// ==========================================
// Language Toggle
// ==========================================
function toggleLanguage() {
    currentLanguage = currentLanguage === "en" ? "km" : "en";
    localStorage.setItem("tgadder_lang", currentLanguage);
    applyLanguage(currentLanguage);
}

function applyLanguage(lang) {
    const dict = I18N[lang] || I18N.en;
    document.getElementById("currentLangLabel").innerText = lang === "km" ? "ខ្មែរ" : "EN";

    for (const [key, value] of Object.entries(dict)) {
        const el = document.getElementById(key);
        if (el) {
            el.innerHTML = value;
        }
    }
    updateAccountsSummary();
}

// ==========================================
// License Countdown Timer
// ==========================================
let _countdownInterval = null;

function startLicenseCountdown(expiresAt) {
    if (_countdownInterval) clearInterval(_countdownInterval);

    // "Lifetime" or null → no countdown needed
    if (!expiresAt || expiresAt === "Lifetime") return;

    const pill = document.getElementById("licenseStatusBtn");
    const dot  = document.getElementById("licenseStatusDot");
    const text = document.getElementById("licenseStatusText");

    let expiresMs;
    try {
        expiresMs = new Date(expiresAt).getTime();
        if (isNaN(expiresMs)) return;
    } catch { return; }

    function tick() {
        const now = Date.now();
        const diff = expiresMs - now;

        if (diff <= 0) {
            clearInterval(_countdownInterval);
            pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-red-950/60 border-red-500/60 text-red-300 animate-pulse";
            dot.className  = "w-2 h-2 rounded-full bg-red-400 animate-ping";
            text.innerText = "⚠️ License EXPIRED";
            document.getElementById("licenseAlertBanner")?.classList.remove("hidden");
            return;
        }

        const totalSecs = Math.floor(diff / 1000);
        const days      = Math.floor(totalSecs / 86400);
        const hours     = Math.floor((totalSecs % 86400) / 3600);
        const mins      = Math.floor((totalSecs % 3600) / 60);
        const secs      = totalSecs % 60;

        let countdown;
        if (days > 0) {
            countdown = `${days}d ${String(hours).padStart(2,"0")}h ${String(mins).padStart(2,"0")}m`;
        } else if (hours > 0) {
            countdown = `${String(hours).padStart(2,"0")}h ${String(mins).padStart(2,"0")}m ${String(secs).padStart(2,"0")}s`;
        } else {
            countdown = `${String(mins).padStart(2,"0")}m ${String(secs).padStart(2,"0")}s`;
        }

        const tier = currentLicense?.tier || "License";
        text.innerText = `${tier} ⏳ ${countdown}`;

        // Colour urgency levels
        if (diff < 2 * 3600 * 1000) {
            // < 2 hours: red flashing
            pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-red-950/60 border-red-500/50 text-red-300";
            dot.className  = "w-2 h-2 rounded-full bg-red-400 animate-ping";
        } else if (diff < 24 * 3600 * 1000) {
            // < 24 hours: amber warning
            pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-amber-950/50 border-amber-500/50 text-amber-200";
            dot.className  = "w-2 h-2 rounded-full bg-amber-400 animate-pulse";
        } else {
            // OK: green
            pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-emerald-950/40 border-emerald-500/40 text-emerald-200 hover:bg-emerald-900/40";
            dot.className  = "w-2 h-2 rounded-full bg-emerald-400";
        }
    }

    tick();
    _countdownInterval = setInterval(tick, 1000);
}

// ==========================================
// License Activation & Status
// ==========================================
async function checkLicenseStatus() {
    const key = getLicenseKey();
    const pill = document.getElementById("licenseStatusBtn");
    const dot = document.getElementById("licenseStatusDot");
    const text = document.getElementById("licenseStatusText");
    const banner = document.getElementById("licenseAlertBanner");

    if (!key) {
        pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-red-950/40 border-red-500/40 text-red-300 hover:bg-red-900/40";
        dot.className = "w-2 h-2 rounded-full bg-red-400 animate-pulse";
        text.innerText = currentLanguage === "km" ? "ត្រូវការ License Key" : "License Required";
        banner.classList.remove("hidden");
        currentLicense = null;
        renderAccounts([]);
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/license/status`, {
            headers: {
                "X-License-Key": key,
                "X-Machine-Id": getMachineId()
            }
        });
        const data = await res.json().catch(() => ({}));
        if (data.is_active && data.license) {
            currentLicense = data.license;
            if (data.license.bound_device) {
                localStorage.setItem("tgadder_machine_id", data.license.bound_device);
                renderMachineId();
            }
            const expiresAt = data.license.expires_at;
            const isLifetime = !expiresAt || expiresAt === "Lifetime";

            if (isLifetime) {
                pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-emerald-950/40 border-emerald-500/40 text-emerald-300 hover:bg-emerald-900/40";
                dot.className = "w-2 h-2 rounded-full bg-emerald-400";
                text.innerText = `${data.license.tier} ♾️ Lifetime`;
            } else {
                // Start the live countdown ticker
                startLicenseCountdown(expiresAt);
            }
            banner.classList.add("hidden");
            loadAccounts();
        } else {
            if (_countdownInterval) clearInterval(_countdownInterval);
            pill.className = "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold bg-amber-950/40 border-amber-500/40 text-amber-300 hover:bg-amber-900/40";
            dot.className = "w-2 h-2 rounded-full bg-amber-400 animate-pulse";
            text.innerText = (data && data.message) ? data.message : "Invalid / Expired License";
            banner.classList.remove("hidden");
            currentLicense = null;
        }
    } catch (e) {
        console.error("License check error:", e);
    }
}

function openLicenseModal() {
    const input = document.getElementById("licenseKeyInput");
    input.value = getLicenseKey();
    document.getElementById("licenseModalError").classList.add("hidden");
    const succEl = document.getElementById("licenseModalSuccess");
    if (succEl) succEl.classList.add("hidden");
    // Render machine ID inside modal
    renderMachineId();
    document.getElementById("licenseModal").classList.remove("hidden");
}

function closeLicenseModal() {
    document.getElementById("licenseModal").classList.add("hidden");
}

function fillDemoKey(key) {
    document.getElementById("licenseKeyInput").value = key;
    document.getElementById("licenseModalError").classList.add("hidden");
    const succEl = document.getElementById("licenseModalSuccess");
    if (succEl) succEl.classList.add("hidden");
}

async function submitLicenseActivation() {
    const rawVal = document.getElementById("licenseKeyInput").value.trim();
    const key = rawVal.replace(/\s+/g, "").toUpperCase();
    document.getElementById("licenseKeyInput").value = key;

    const errBox = document.getElementById("licenseModalError");
    const succBox = document.getElementById("licenseModalSuccess");
    errBox.classList.add("hidden");
    if (succBox) succBox.classList.add("hidden");

    if (!key) {
        errBox.innerText = currentLanguage === "km"
            ? "សូមបញ្ចូល License Key ។"
            : "Please enter a valid license key.";
        errBox.classList.remove("hidden");
        return;
    }

    if (key.startsWith("MID-")) {
        errBox.innerText = currentLanguage === "km"
            ? "នេះជា Machine ID របស់អ្នក មិនមែនជា License Key ទេ។ សូមចុចប៊ូតុង 'ចម្លង ID និងស្នើ License ពី Admin' ដើម្បីទទួល License Key ពី Admin @kun_amra!"
            : "This is your Machine ID, not a License Key! Please click 'Copy ID & Request License' above to request a key from Admin @kun_amra.";
        errBox.classList.remove("hidden");
        return;
    }

    const btn = document.getElementById("btnActivateKey");
    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-circle-notch fa-spin mr-2"></i> Verifying...`;

    try {
        const res = await fetch(`${API_BASE}/api/license/activate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                license_key: key,
                machine_id: getMachineId()
            })
        });

        const data = await res.json().catch(() => ({}));

        if (res.ok && data && data.success) {
            setLicenseKey(key.toUpperCase());
            if (data.license && data.license.bound_device) {
                localStorage.setItem("tgadder_machine_id", data.license.bound_device);
                renderMachineId();
            }
            if (succBox) {
                succBox.innerText = currentLanguage === "km"
                    ? "✅ License Key ត្រឹមត្រូវ! ឧបករណ៍ត្រូវបានដោះសោជោគជ័យ!"
                    : "✅ License activated! Tool unlocked successfully!";
                succBox.classList.remove("hidden");
            }
            setTimeout(async () => {
                closeLicenseModal();
                await checkLicenseStatus();
                logConsole(`License key activated! Tier: ${data.license?.tier || ""}. Tool unlocked.`, "success");
            }, 800);
        } else {
            const errorMsg = (data && (data.message || data.detail)) || `Server returned error (${res.status})`;
            errBox.innerText = errorMsg;
            errBox.classList.remove("hidden");
        }
    } catch (err) {
        console.error("Activation network error:", err);
        errBox.innerText = currentLanguage === "km"
            ? `បញ្ហាតភ្ជាប់: ${err.message || 'ម៉ាស៊ីនបម្រើ (Web Server) មិនទាន់ដំណើរការទេ។ សូមចុច run_web.bat ជាមុនសិន!'}`
            : `Connection error: ${err.message || 'Cannot reach server. Please make sure run_web.bat is running.'}`;
        errBox.classList.remove("hidden");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fas fa-unlock-alt mr-2"></i> Activate License Key`;
    }
}

// ==========================================
// Accounts Management
// ==========================================
async function loadAccounts() {
    if (!getLicenseKey()) return;
    try {
        const res = await fetch(`${API_BASE}/api/accounts`, { headers: getAuthHeaders() });
        if (res.status === 403) {
            openLicenseModal();
            return;
        }
        const data = await res.json();
        if (data.success) {
            const serverAccounts = data.accounts || [];
            if (serverAccounts.length > 0) {
                // Merge server accounts with localStorage — keep session_string from cache if server lost it
                const cachedRaw = localStorage.getItem(getAccountsStorageKey());
                let cachedMap = {};
                if (cachedRaw) {
                    try {
                        const cached = JSON.parse(cachedRaw);
                        if (Array.isArray(cached)) {
                            cached.forEach(a => { if (a.phone_number) cachedMap[a.phone_number] = a; });
                        }
                    } catch (e) {}
                }
                currentAccounts = serverAccounts.map(acc => {
                    const cached = cachedMap[acc.phone_number];
                    if (cached && cached.session_string && !acc.session_string) {
                        // Restore session_string from localStorage if server doesn't have it
                        return Object.assign({}, acc, { session_string: cached.session_string });
                    }
                    return acc;
                });
                saveAccountsToLocalStorage(currentAccounts);
            } else {
                // If server accounts are empty (e.g. server restart), check localStorage cache
                const cachedRaw = localStorage.getItem(getAccountsStorageKey());
                if (cachedRaw) {
                    try {
                        const cached = JSON.parse(cachedRaw);
                        if (Array.isArray(cached) && cached.length > 0) {
                            currentAccounts = cached;
                            // Sync back to server so server is also up-to-date
                            fetch(`${API_BASE}/api/accounts/sync-cache`, {
                                method: "POST",
                                headers: getAuthHeaders(),
                                body: JSON.stringify({ accounts: cached })
                            }).catch(() => {});
                        } else {
                            currentAccounts = [];
                            saveAccountsToLocalStorage([]);
                        }
                    } catch (e) {
                        currentAccounts = [];
                    }
                } else {
                    currentAccounts = [];
                }
            }
            renderAccounts(currentAccounts);
            updateAccountsSummary(data.max_accounts);
        }
    } catch (e) {
        console.error("Load accounts error:", e);
        // On network error or server waking up, preserve cached accounts from localStorage!
        loadAccountsFromLocalStorage();
    }
}

function updateAccountsSummary(max = 50) {
    const total = currentAccounts.length;
    const active = currentAccounts.filter(a => a.enabled).length;
    const counterEl = document.getElementById("accountsCounter");
    if (counterEl) {
        counterEl.innerText = currentLanguage === "km" 
            ? `សកម្ម: ${active} នៃ ${total} (អតិបរមា: ${max})`
            : `Active: ${active} of ${total} (Max: ${max})`;
    }
}

function renderAccounts(accounts) {
    const listEl = document.getElementById("accountsList");
    if (!accounts || accounts.length === 0) {
        listEl.innerHTML = `
            <div class="text-center py-8 text-gray-500 text-xs" id="emptyAccountsMsg">
                <i class="fas fa-user-slash text-2xl mb-2 block text-gray-600"></i>
                ${I18N[currentLanguage].emptyAccounts}
            </div>
        `;
        return;
    }

    listEl.innerHTML = accounts.map(acc => {
        const isPrem    = acc.is_premium;
        const isSpam    = acc.spam_flagged;
        const isDisabled = !acc.enabled;

        // Badges
        const premBadge = isPrem
            ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">⭐ Premium</span>`
            : "";
        const spamBadge = isSpam
            ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse">⚠️ Spam</span>`
            : "";
        const needsAuthBadge = (!acc.session_string || acc.needs_reauth)
            ? `<button onclick="openAddAccountModal(); switchLoginMode('phone'); const pi=document.getElementById('inputPhone'); if(pi) pi.value='${acc.phone_number}';" title="Session needs authorization on cloud. Click to re-login." class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/40 cursor-pointer">🔑 Re-login</button>`
            : "";

        const fullName = `${acc.first_name || ""} ${acc.last_name || ""}`.trim() || acc.username || acc.phone_number;
        const userTag  = acc.username ? `<span class="text-gray-400 text-xs">@${acc.username}</span>` : "";

        // Avatar color: red if spam, amber if premium, cyan default
        const avatarColor = isSpam
            ? "bg-red-500/20 text-red-400 border border-red-500/40"
            : isPrem
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                : "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30";

        // Card border: red if spam
        const cardBorder = isSpam ? "border-red-500/40 bg-red-900/10" : "border-gray-800 bg-gray-900/80";

        // Clear spam button (only when flagged)
        const clearSpamBtn = isSpam
            ? `<button onclick="clearSpam('${acc.phone_number}')" title="Clear spam flag" class="w-7 h-7 rounded-lg hover:bg-orange-500/20 text-red-400 hover:text-orange-400 flex items-center justify-center transition text-xs">
                <i class="fas fa-times-circle"></i>
               </button>`
            : "";

        return `
            <div class="${cardBorder} border rounded-xl p-3 flex items-center justify-between gap-3 hover:border-gray-700 transition">
                <div class="flex items-center gap-3 min-w-0">
                    <div class="w-9 h-9 rounded-full ${avatarColor} flex items-center justify-center font-bold text-xs shrink-0">
                        ${acc.first_name ? acc.first_name.charAt(0).toUpperCase() : 'T'}
                    </div>
                    <div class="min-w-0 truncate">
                        <div class="flex items-center gap-1.5 flex-wrap">
                            <span class="text-xs font-semibold text-white truncate">${fullName}</span>
                            ${premBadge}
                            ${spamBadge}
                            ${needsAuthBadge}
                        </div>
                        <div class="flex items-center gap-2 text-[11px] text-gray-400">
                            <span class="font-mono">${acc.phone_number}</span>
                            ${userTag}
                        </div>
                    </div>
                </div>

                <div class="flex items-center gap-2 shrink-0">
                    <!-- Toggle Checkbox Switch -->
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" ${acc.enabled ? "checked" : ""} onchange="toggleAccount('${acc.phone_number}', this.checked)" class="sr-only peer">
                        <div class="w-9 h-5 bg-gray-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-cyan-600"></div>
                    </label>

                    ${clearSpamBtn}

                    <!-- Delete Button -->
                    <button onclick="deleteAccount('${acc.phone_number}')" class="w-7 h-7 rounded-lg hover:bg-red-500/20 text-gray-500 hover:text-red-400 flex items-center justify-center transition">
                        <i class="fas fa-trash text-xs"></i>
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

async function toggleAccount(phone, enabled) {
    try {
        await fetch(`${API_BASE}/api/accounts/toggle`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ phone, enabled })
        });
        loadAccounts();
    } catch (e) {
        console.error(e);
    }
}

async function deleteAccount(phone) {
    if (!confirm(currentLanguage === "km" ? `តើអ្នកពិតជាចង់លុបគណនី ${phone} ឬ?` : `Are you sure you want to remove ${phone}?`)) {
        return;
    }
    // Optimistically remove from localStorage cache immediately
    currentAccounts = currentAccounts.filter(a => a.phone_number !== phone);
    saveAccountsToLocalStorage(currentAccounts);
    renderAccounts(currentAccounts);
    updateAccountsSummary();

    try {
        await fetch(`${API_BASE}/api/accounts/${encodeURIComponent(phone)}`, {
            method: "DELETE",
            headers: getAuthHeaders()
        });
        loadAccounts();
    } catch (e) {
        console.error(e);
    }
}

async function clearSpam(phone) {
    // Clear spam_flagged flag on an account
    try {
        const acc = currentAccounts.find(a => a.phone_number === phone);
        if (acc) {
            acc.spam_flagged = false;
            saveAccountsToLocalStorage(currentAccounts);
            renderAccounts(currentAccounts);
        }
        await fetch(`${API_BASE}/api/accounts/clear-spam`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ phone })
        });
        loadAccounts();
    } catch (e) {
        console.error(e);
    }
}

async function selectAllAccounts(enabled) {
    for (const acc of currentAccounts) {
        await fetch(`${API_BASE}/api/accounts/toggle`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ phone: acc.phone_number, enabled })
        });
    }
    loadAccounts();
}

async function clearAllAccounts() {
    if (!confirm(currentLanguage === "km" ? "តើអ្នកចង់លុបគណនីទាំងអស់មែនទេ?" : "Are you sure you want to remove ALL connected accounts?")) {
        return;
    }
    // Optimistically clear localStorage cache
    currentAccounts = [];
    saveAccountsToLocalStorage([]);
    renderAccounts([]);
    updateAccountsSummary();

    try {
        await fetch(`${API_BASE}/api/accounts/clear-all`, {
            method: "POST",
            headers: getAuthHeaders()
        });
        loadAccounts();
    } catch (e) {
        console.error(e);
    }
}

// ==========================================
// Add Account Modal Wizard & Helpers
// ==========================================
function fillDefaultApiCredentials(preset = "desktop") {
    // Standard Telegram official application credentials
    const credentials = {
        desktop: {
            api_id: 2040,
            api_hash: "b18441a1ff607e10a989891a5462e627"
        },
        android: {
            api_id: 6,
            api_hash: "eb06d4abfb49dc3eeb1aeb98ae0f581e"
        }
    };
    const cred = credentials[preset] || credentials.desktop;
    const inputId = document.getElementById("inputApiId");
    const inputHash = document.getElementById("inputApiHash");
    if (inputId) inputId.value = cred.api_id;
    if (inputHash) inputHash.value = cred.api_hash;

    const errBox = document.getElementById("accountModalError");
    if (errBox) errBox.classList.add("hidden");

    logConsole(`Auto-filled Telegram ${preset === "android" ? "Android" : "Desktop"} API ID & Hash`, "info");
}

function openGetHashUrl() {
    window.open("https://my.telegram.org/apps", "_blank");
}

function openAddAccountModal() {
    if (!getLicenseKey()) {
        openLicenseModal();
        return;
    }
    document.getElementById("stepAccountCredentials").classList.remove("hidden");
    document.getElementById("stepAccountCode").classList.add("hidden");
    document.getElementById("accountModalError").classList.add("hidden");
    document.getElementById("codeModalError").classList.add("hidden");
    
    // Reset 2FA field and OTP input
    const field2Fa = document.getElementById("field2FaPassword");
    if (field2Fa) field2Fa.classList.add("hidden");
    const inputOtp = document.getElementById("inputOtpCode");
    if (inputOtp) inputOtp.value = "";
    const input2Fa = document.getElementById("input2FaPassword");
    if (input2Fa) input2Fa.value = "";

    const btnSubmit = document.getElementById("btnSubmitOtp");
    if (btnSubmit) {
        btnSubmit.innerHTML = `<i class="fas fa-check-circle"></i> <span id="btnSubmitOtpText">${I18N[currentLanguage].btnSubmitOtpText || 'Confirm Account'}</span>`;
    }

    // Start a completely fresh phone-login stage.
    currentLoginPhone = "";
    currentLoginPhoneCodeHash = "";
    currentLoginApiId = null;
    currentLoginApiHash = "";
    currentLoginNeedsPassword = false;
    qrAutoRefreshCount = 0;

    const hint = document.getElementById("codeSentHint");
    if (hint) hint.innerText = "";

    document.getElementById("addAccountModal").classList.remove("hidden");

    // Auto-fill official default API credentials if empty for convenience
    const idInput = document.getElementById("inputApiId");
    const hashInput = document.getElementById("inputApiHash");
    if (idInput && !idInput.value) idInput.value = 2040;
    if (hashInput && !hashInput.value) hashInput.value = "b18441a1ff607e10a989891a5462e627";

    // Default to Phone OTP Mode (reliable across all Telegram Desktop & mobile versions)
    switchLoginMode("phone");
    setTimeout(() => {
        const phoneInput = document.getElementById("inputPhone");
        if (phoneInput) phoneInput.focus();
    }, 150);
}

function cancelQrSession(qrId) {
    if (!qrId) return;
    fetch(`${API_BASE}/api/accounts/qr-login/close/${encodeURIComponent(qrId)}`, {
        method: "POST",
        headers: getAuthHeaders(),
        keepalive: true
    }).catch(() => {});
}

function closeAddAccountModal() {
    document.getElementById("addAccountModal").classList.add("hidden");
    if (qrPollTimer) {
        clearInterval(qrPollTimer);
        qrPollTimer = null;
    }
    const qrIdToCancel = currentQrId;
    currentQrId = null;
    // Do not leave a live QR login socket behind when the modal is closed.
    cancelQrSession(qrIdToCancel);
}

let currentQrId = null;
let qrPollTimer = null;
let qrStarting = false;
let qrAutoRefreshCount = 0;

// Pending phone-login state. The phone_code_hash is sent back to the server on
// verification so a server restart or a second worker cannot lose the login.
let currentLoginPhone = "";
let currentLoginPhoneCodeHash = "";
let currentLoginApiId = null;
let currentLoginApiHash = "";
let currentLoginNeedsPassword = false;

function switchLoginMode(mode) {
    const tabQr = document.getElementById("tabLoginQr");
    const tabPhone = document.getElementById("tabLoginPhone");
    const panelQr = document.getElementById("panelLoginQr");
    const panelPhone = document.getElementById("panelLoginPhone");

    if (mode === "qr") {
        if (tabQr) tabQr.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg transition bg-cyan-600 text-white shadow-sm flex items-center justify-center gap-1.5";
        if (tabPhone) tabPhone.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg transition text-gray-400 hover:text-white flex items-center justify-center gap-1.5";
        if (panelQr) panelQr.classList.remove("hidden");
        if (panelPhone) panelPhone.classList.add("hidden");
        qrAutoRefreshCount = 0;
        if (!currentQrId && !qrStarting) {
            startQrLogin(false);
        }
    } else {
        if (tabPhone) tabPhone.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg transition bg-cyan-600 text-white shadow-sm flex items-center justify-center gap-1.5";
        if (tabQr) tabQr.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg transition text-gray-400 hover:text-white flex items-center justify-center gap-1.5";
        if (panelPhone) panelPhone.classList.remove("hidden");
        if (panelQr) panelQr.classList.add("hidden");
        if (qrPollTimer) {
            clearInterval(qrPollTimer);
            qrPollTimer = null;
        }
        // Release the live QR socket if the user switches back to phone login.
        const qrIdToCancel = currentQrId;
        currentQrId = null;
        cancelQrSession(qrIdToCancel);
    }
}

async function startQrLogin(isAuto = false) {
    if (qrStarting) return;
    qrStarting = true;
    if (!isAuto) qrAutoRefreshCount = 0;

    if (qrPollTimer) {
        clearInterval(qrPollTimer);
        qrPollTimer = null;
    }
    // Cancel the previous QR (if any) before generating a new one.
    const oldQrId = currentQrId;
    currentQrId = null;
    cancelQrSession(oldQrId);

    const qrLoading = document.getElementById("qrLoadingState");
    const qrContent = document.getElementById("qrContentState");
    const qr2Fa = document.getElementById("qr2FaCard");
    const qrErr = document.getElementById("qrModalError");

    if (qrLoading) qrLoading.classList.remove("hidden");
    if (qrContent) qrContent.classList.add("hidden");
    if (qr2Fa) qr2Fa.classList.add("hidden");
    if (qrErr) qrErr.classList.add("hidden");

    const apiIdInput = document.getElementById("inputApiId");
    const apiHashInput = document.getElementById("inputApiHash");
    const apiId = parseInt(apiIdInput && apiIdInput.value.trim()) || 2040;
    const apiHash = (apiHashInput && apiHashInput.value.trim()) || "b18441a1ff607e10a989891a5462e627";

    try {
        const res = await fetch(`${API_BASE}/api/accounts/qr-login/start`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ api_id: apiId, api_hash: apiHash })
        });
        const data = await res.json();

        if (res.ok && data.success && data.data) {
            const qrInfo = data.data;
            currentQrId = qrInfo.qr_id;

            const qrImg = document.getElementById("qrCodeImg");
            if (qrImg) qrImg.src = qrInfo.qr_image;

            const btnOpen = document.getElementById("btnOpenTgLink");
            if (btnOpen) {
                btnOpen.href = qrInfo.url;
            }

            if (qrLoading) qrLoading.classList.add("hidden");
            if (qrContent) qrContent.classList.remove("hidden");

            // Start polling for status
            startPollingQrStatus(qrInfo.qr_id);
            logConsole("Telegram Login QR generated. Confirm on your device!", "info");
        } else {
            if (qrLoading) qrLoading.classList.add("hidden");
            if (qrErr) {
                qrErr.innerText = data.detail || data.message || "Failed to generate QR Code.";
                qrErr.classList.remove("hidden");
            }
        }
    } catch (err) {
        if (qrLoading) qrLoading.classList.add("hidden");
        if (qrErr) {
            qrErr.innerText = "Error: " + err.message;
            qrErr.classList.remove("hidden");
        }
    } finally {
        qrStarting = false;
    }
}

function stopQrPolling() {
    if (qrPollTimer) {
        clearInterval(qrPollTimer);
        qrPollTimer = null;
    }
}

function startPollingQrStatus(qrId) {
    stopQrPolling();

    qrPollTimer = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/accounts/qr-login/status/${qrId}`, {
                headers: getAuthHeaders()
            });
            const data = await res.json();

            if (res.status === 403) {
                stopQrPolling();
                const qrErr = document.getElementById("qrModalError");
                if (qrErr) {
                    qrErr.innerText = data.detail || "License error. Please activate your license again.";
                    qrErr.classList.remove("hidden");
                }
                return;
            }
            if (!data.success || !data.data) return;

            const st = data.data;
            if (st.status === "waiting") {
                if (st.qr_image) {
                    const qrImg = document.getElementById("qrCodeImg");
                    if (qrImg && qrImg.src !== st.qr_image) qrImg.src = st.qr_image;
                }
                if (st.url) {
                    const btnOpen = document.getElementById("btnOpenTgLink");
                    if (btnOpen) btnOpen.href = st.url;
                }
            } else if (st.status === "success") {
                stopQrPolling();
                currentQrId = null;
                if (st.account) {
                    const idx = currentAccounts.findIndex(a => a.phone_number === st.account.phone_number);
                    if (idx >= 0) {
                        currentAccounts[idx] = Object.assign({}, currentAccounts[idx], st.account);
                    } else {
                        currentAccounts.push(st.account);
                    }
                    saveAccountsToLocalStorage(currentAccounts);
                    renderAccounts(currentAccounts);
                    updateAccountsSummary();
                }
                closeAddAccountModal();
                loadAccounts();
                const phone = st.phone || (st.account && st.account.phone_number) || "";
                logConsole(`Telegram Account ${phone} successfully logged in via QR!`, "success");
            } else if (st.status === "needs_2fa") {
                // The QR was confirmed. Stop polling and let the user submit
                // the cloud password; the socket stays alive on the server.
                stopQrPolling();
                const qr2Fa = document.getElementById("qr2FaCard");
                if (qr2Fa) {
                    qr2Fa.classList.remove("hidden");
                    const input = document.getElementById("inputQr2FaPassword");
                    if (input) input.focus();
                }
                const statusMsg = document.getElementById("txtQrStatusMsg");
                if (statusMsg) {
                    statusMsg.innerText = currentLanguage === "km"
                        ? "🔐 គណនីមាន 2FA! សូមបញ្ចូលលេខកូដ 2FA របស់អ្នក"
                        : "🔐 QR confirmed! Enter your Telegram 2FA password below.";
                }
            } else if (st.status === "expired") {
                stopQrPolling();
                const statusMsg = document.getElementById("txtQrStatusMsg");
                const modalOpen = !document.getElementById("addAccountModal").classList.contains("hidden");
                if (modalOpen && qrAutoRefreshCount < 20) {
                    qrAutoRefreshCount += 1;
                    if (statusMsg) {
                        statusMsg.innerText = currentLanguage === "km"
                            ? "QR Code ផុតកំណត់! កំពុងបង្កើត QR ថ្មី..."
                            : `QR expired. Generating a fresh QR (${qrAutoRefreshCount}/20)...`;
                    }
                    setTimeout(() => startQrLogin(true), 1200);
                } else if (statusMsg) {
                    statusMsg.innerText = currentLanguage === "km"
                        ? "QR Code ផុតកំណត់! សូមចុច Refresh"
                        : "QR expired. Please click Refresh QR Code.";
                }
            } else if (st.status === "not_found") {
                stopQrPolling();
                const statusMsg = document.getElementById("txtQrStatusMsg");
                if (statusMsg) {
                    statusMsg.innerText = "This QR session was closed. Click Refresh QR Code to start again.";
                }
            } else if (st.status === "error") {
                stopQrPolling();
                const qrErr = document.getElementById("qrModalError");
                if (qrErr) {
                    qrErr.innerText = st.error || "Login failed.";
                    qrErr.classList.remove("hidden");
                }
            }
        } catch (e) {
            // network glitch, keep polling
        }
    }, 1500);
}

async function submitQr2FaPassword() {
    if (!currentQrId) return;
    const password = document.getElementById("inputQr2FaPassword").value;
    const errBox = document.getElementById("qr2FaError");
    const btn = document.getElementById("btnSubmitQr2Fa");

    if (errBox) errBox.classList.add("hidden");

    if (!password) {
        if (errBox) {
            errBox.innerText = currentLanguage === "km" ? "សូមបញ្ចូលលេខកូដសម្ងាត់ 2FA!" : "Please enter your 2FA password!";
            errBox.classList.remove("hidden");
        }
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Verifying...`;

    try {
        const res = await fetch(`${API_BASE}/api/accounts/qr-login/2fa`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ qr_id: currentQrId, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (qrPollTimer) clearInterval(qrPollTimer);
            qrPollTimer = null;
            currentQrId = null;
            if (data.data && data.data.account) {
                const acc = data.data.account;
                const idx = currentAccounts.findIndex(a => a.phone_number === acc.phone_number);
                if (idx >= 0) {
                    currentAccounts[idx] = Object.assign({}, currentAccounts[idx], acc);
                } else {
                    currentAccounts.push(acc);
                }
                saveAccountsToLocalStorage(currentAccounts);
                renderAccounts(currentAccounts);
                updateAccountsSummary();
            }
            closeAddAccountModal();
            loadAccounts();
            logConsole("Account logged in successfully with 2FA password!", "success");
        } else {
            if (errBox) {
                errBox.innerText = data.detail || data.message || "Incorrect 2FA password.";
                errBox.classList.remove("hidden");
            }
        }
    } catch (e) {
        if (errBox) {
            errBox.innerText = "Error: " + e.message;
            errBox.classList.remove("hidden");
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fas fa-key"></i> <span>Confirm 2FA Password</span>`;
    }
}

function backToStep1() {
    document.getElementById("stepAccountCredentials").classList.remove("hidden");
    document.getElementById("stepAccountCode").classList.add("hidden");
    document.getElementById("codeModalError").classList.add("hidden");
}

function toggle2FaField() {
    const field = document.getElementById("field2FaPassword");
    if (!field) return;
    const isHidden = field.classList.contains("hidden");
    if (isHidden) {
        field.classList.remove("hidden");
        const input2Fa = document.getElementById("input2FaPassword");
        if (input2Fa) input2Fa.focus();
    } else {
        field.classList.add("hidden");
    }
}

async function requestTelegramCode(triggerButtonId = "btnSendCode", isResend = false) {
    const apiId = parseInt(document.getElementById("inputApiId").value.trim());
    const apiHash = document.getElementById("inputApiHash").value.trim();
    const phone = document.getElementById("inputPhone").value.trim();
    const errBox = document.getElementById("accountModalError");
    const btn = document.getElementById(triggerButtonId) || document.getElementById("btnSendCode");
    const originalBtnHtml = btn ? btn.innerHTML : "";

    errBox.classList.add("hidden");

    if (!apiId || !apiHash || !phone) {
        errBox.innerText = currentLanguage === "km"
            ? "សូមបំពេញ API ID, API Hash និងលេខទូរស័ព្ទ!"
            : "Please fill in API ID, API Hash, and Phone Number.";
        errBox.classList.remove("hidden");
        if (!isResend) {
            document.getElementById("stepAccountCredentials").classList.remove("hidden");
            document.getElementById("stepAccountCode").classList.add("hidden");
        }
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> ${isResend ? (currentLanguage === "km" ? "កំពុងផ្ញើកូដថ្មី..." : "Resending...") : (currentLanguage === "km" ? "កំពុងស្នើសុំកូដ..." : "Sending Request...")}`;
    }

    try {
        const res = await fetch(`${API_BASE}/api/accounts/request-code`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ api_id: apiId, api_hash: apiHash, phone })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            if (data.data && data.data.already_authorized) {
                currentLoginNeedsPassword = false;
                if (data.data.account) {
                    const acc = data.data.account;
                    const idx = currentAccounts.findIndex(a => a.phone_number === acc.phone_number);
                    if (idx >= 0) {
                        currentAccounts[idx] = Object.assign({}, currentAccounts[idx], acc);
                    } else {
                        currentAccounts.push(acc);
                    }
                    saveAccountsToLocalStorage(currentAccounts);
                    renderAccounts(currentAccounts);
                    updateAccountsSummary();
                }
                closeAddAccountModal();
                loadAccounts();
                logConsole(`Account ${phone} is already authorized!`, "success");
            } else {
                const normalizedPhone = (data.data && data.data.phone) || phone;
                const delivery = (data.data && data.data.delivery) || data.message || "";

                // Remember everything needed to verify even if the server
                // restarts between these two requests.
                currentLoginPhone = normalizedPhone;
                currentLoginPhoneCodeHash = (data.data && data.data.phone_code_hash) || "";
                currentLoginApiId = apiId;
                currentLoginApiHash = apiHash;
                currentLoginNeedsPassword = false;

                document.getElementById("codeSentPhone").innerText = normalizedPhone;
                const hint = document.getElementById("codeSentHint");
                if (hint) {
                    hint.innerText = delivery
                        ? `${delivery} If it does not arrive, wait a minute and click Resend Code.`
                        : "If the code does not arrive, wait a minute and click Resend Code.";
                }
                document.getElementById("inputOtpCode").value = "";
                document.getElementById("input2FaPassword").value = "";
                document.getElementById("field2FaPassword").classList.add("hidden");
                document.getElementById("codeModalError").classList.add("hidden");

                // Switch view to Step 2 (Enter OTP code)
                document.getElementById("stepAccountCredentials").classList.add("hidden");
                document.getElementById("stepAccountCode").classList.remove("hidden");
                document.getElementById("btnSubmitOtp").innerHTML = `<i class="fas fa-check-circle"></i> <span id="btnSubmitOtpText">${I18N[currentLanguage].btnSubmitOtpText || 'Confirm Account'}</span>`;

                // Auto-focus OTP input
                setTimeout(() => {
                    const otpInput = document.getElementById("inputOtpCode");
                    if (otpInput) otpInput.focus();
                }, 150);

                logConsole(`Telegram login code sent to ${normalizedPhone}. ${delivery}`, "info");
            }
        } else {
            const msg = data.detail || data.message || "Failed to request code.";
            errBox.innerText = msg;
            errBox.classList.remove("hidden");
            if (isResend) {
                document.getElementById("codeModalError").innerText = msg;
                document.getElementById("codeModalError").className = "text-xs text-red-400 bg-red-950/40 border border-red-800 rounded-lg p-2.5";
                document.getElementById("codeModalError").classList.remove("hidden");
            }
        }
    } catch (err) {
        errBox.innerText = "Error: " + err.message;
        errBox.classList.remove("hidden");
        if (isResend) {
            const codeErr = document.getElementById("codeModalError");
            codeErr.innerText = "Error: " + err.message;
            codeErr.classList.remove("hidden");
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalBtnHtml;
        }
    }
}

function resendTelegramCode() {
    return requestTelegramCode("btnResendCode", true);
}

async function verifyTelegramCode() {
    const phone = currentLoginPhone || document.getElementById("codeSentPhone").innerText;
    const code = document.getElementById("inputOtpCode").value.trim();
    const password = document.getElementById("input2FaPassword").value;
    const errBox = document.getElementById("codeModalError");
    const btn = document.getElementById("btnSubmitOtp");
    const field2Fa = document.getElementById("field2FaPassword");

    errBox.classList.add("hidden");

    // Only force the password field when Telegram actually told us 2FA is on.
    if (currentLoginNeedsPassword && !password) {
        errBox.innerText = currentLanguage === "km"
            ? "សូមបញ្ចូលលេខកូដសម្ងាត់ Two-Step Verification (2FA) របស់អ្នក!"
            : "Please enter your 2FA Password to proceed.";
        errBox.className = "text-xs text-amber-400 bg-amber-950/40 border border-amber-800 rounded-lg p-2.5";
        errBox.classList.remove("hidden");
        document.getElementById("input2FaPassword").focus();
        return;
    }

    if (!currentLoginNeedsPassword && !code) {
        errBox.innerText = currentLanguage === "km"
            ? "សូមបញ្ចូលលេខកូដបញ្ជាក់ (OTP Code) ដែល Telegram បានផ្ញើទៅ!"
            : "Please enter the confirmation code from Telegram.";
        errBox.className = "text-xs text-red-400 bg-red-950/40 border border-red-800 rounded-lg p-2.5";
        errBox.classList.remove("hidden");
        document.getElementById("inputOtpCode").focus();
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> ${currentLanguage === "km" ? "កំពុងផ្ទៀងផ្ទាត់..." : "Verifying..."}`;

    try {
        const res = await fetch(`${API_BASE}/api/accounts/verify-code`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({
                phone,
                code: currentLoginNeedsPassword ? "" : code,
                password: password || null,
                phone_code_hash: currentLoginPhoneCodeHash,
                api_id: currentLoginApiId,
                api_hash: currentLoginApiHash,
                password_stage: currentLoginNeedsPassword
            })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            // Check if Telegram requires 2FA password
            if (data.data && data.data.needs_password) {
                currentLoginNeedsPassword = true;
                field2Fa.classList.remove("hidden");
                errBox.innerText = currentLanguage === "km"
                    ? "🔐 គណនីនេះបានបើក Two-Step Verification (2FA)! សូមបញ្ចូលលេខកូដសម្ងាត់ 2FA របស់អ្នក។"
                    : (data.message || "2FA Password required. Please enter your Telegram 2FA password.");
                errBox.className = "text-xs text-amber-400 bg-amber-950/40 border border-amber-800 rounded-lg p-2.5";
                errBox.classList.remove("hidden");

                setTimeout(() => {
                    const pwdInput = document.getElementById("input2FaPassword");
                    if (pwdInput) pwdInput.focus();
                }, 100);
            } else {
                // Successfully signed in!
                currentLoginNeedsPassword = false;
                currentLoginPhone = "";
                currentLoginPhoneCodeHash = "";
                if (data.data && data.data.account) {
                    const acc = data.data.account;
                    const idx = currentAccounts.findIndex(a => a.phone_number === acc.phone_number);
                    if (idx >= 0) {
                        currentAccounts[idx] = Object.assign({}, currentAccounts[idx], acc);
                    } else {
                        currentAccounts.push(acc);
                    }
                    saveAccountsToLocalStorage(currentAccounts);
                    renderAccounts(currentAccounts);
                    updateAccountsSummary();
                }
                closeAddAccountModal();
                loadAccounts();
                logConsole(data.message || `Account ${phone} successfully connected!`, "success");
            }
        } else {
            // Error occurred (e.g. incorrect 2FA password, wrong OTP, etc.)
            const msg = data.detail || data.message || "Verification failed.";
            const details = data.data || {};
            errBox.innerText = msg;
            errBox.className = "text-xs text-red-400 bg-red-950/40 border border-red-800 rounded-lg p-2.5";
            errBox.classList.remove("hidden");

            if (details.needs_password || msg.toLowerCase().includes("2fa") || msg.toLowerCase().includes("password")) {
                currentLoginNeedsPassword = true;
                field2Fa.classList.remove("hidden");
                setTimeout(() => {
                    const pwdInput = document.getElementById("input2FaPassword");
                    if (pwdInput) pwdInput.focus();
                }, 100);
            } else if (details.can_resend) {
                const resendBtn = document.getElementById("btnResendCode");
                if (resendBtn) resendBtn.focus();
            }
        }
    } catch (err) {
        errBox.innerText = "Error: " + err.message;
        errBox.className = "text-xs text-red-400 bg-red-950/40 border border-red-800 rounded-lg p-2.5";
        errBox.classList.remove("hidden");
    } finally {
        btn.disabled = false;
        if (currentLoginNeedsPassword) {
            btn.innerHTML = `<i class="fas fa-lock"></i> <span id="btnSubmitOtpText">${currentLanguage === "km" ? "បញ្ជាក់ជាមួយ 2FA Password" : "Confirm with 2FA Password"}</span>`;
        } else {
            btn.innerHTML = `<i class="fas fa-check-circle"></i> <span id="btnSubmitOtpText">${I18N[currentLanguage].btnSubmitOtpText || 'Confirm Account'}</span>`;
        }
    }
}

// ==========================================
// Scraper & Member Management
// ==========================================
async function fetchSourceMembers() {
    if (!getLicenseKey()) {
        openLicenseModal();
        return;
    }
    const sourceGroup = document.getElementById("sourceGroupInput").value.trim();
    const btn = document.getElementById("btnFetchMembers");

    if (!sourceGroup) {
        alert(currentLanguage === "km" ? "សូមបញ្ចូលតំណភ្ជាប់ក្រុមប្រភព!" : "Please enter the source group link or username!");
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Fetching...`;

    try {
        const res = await fetch(`${API_BASE}/api/members/scrape`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({
                source_group: sourceGroup,
                accounts_override: currentAccounts
            })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            const fetched = data.data.members || [];
            appendMembersToTextarea(fetched);
            logConsole(`Scraped ${fetched.length} members from ${sourceGroup} (Filtered ${data.data.deleted_count} deleted, ${data.data.bot_count} bots)`, "success");
        } else {
            const errMsg = data.detail || data.message || "Could not fetch members.";
            logConsole(`Scrape Error: ${errMsg}`, "error");
            if (errMsg.toLowerCase().includes("not authorized") || errMsg.toLowerCase().includes("re-login")) {
                const m = errMsg.match(/\+?\d{7,15}/);
                const unauthPhone = m ? m[0] : "";
                if (unauthPhone) {
                    currentAccounts.forEach(a => {
                        if (a.phone_number === unauthPhone) {
                            a.needs_reauth = true;
                            a.session_string = "";
                        }
                    });
                    saveAccountsToLocalStorage(currentAccounts);
                    renderAccounts(currentAccounts);
                }
                const promptMsg = currentLanguage === "km"
                    ? `គណនី ${unauthPhone || ""} ផុតកំណត់ការអនុញ្ញាត (Unauthorized)។ សូមចុចប៊ូតុង "🔑 Re-login" លើគណនីនោះដើម្បីភ្ជាប់ឡើងវិញ!`
                    : `Account ${unauthPhone || ""} is not authorized. Please click "🔑 Re-login" next to the account to reconnect.`;
                alert(promptMsg);
            } else {
                alert(errMsg);
            }
        }
    } catch (err) {
        logConsole(`Scraping network error: ${err.message}`, "error");
        alert("Scraping error: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fas fa-download"></i> <span id="btnFetchText">${I18N[currentLanguage].btnFetchText}</span>`;
    }
}

function appendMembersToTextarea(newMembers) {
    const textarea = document.getElementById("memberListTextarea");
    const current = textarea.value.split("\n").map(s => s.trim()).filter(Boolean);
    const combined = Array.from(new Set([...current, ...newMembers]));
    textarea.value = combined.join("\n");
    updateCandidatesCount();
}

function updateCandidatesCount() {
    const textarea = document.getElementById("memberListTextarea");
    const lines = textarea.value.split("\n").map(s => s.trim()).filter(Boolean);
    document.getElementById("membersCount").innerText = lines.length;
}

function cleanAndDeduplicate() {
    const textarea = document.getElementById("memberListTextarea");
    const raw = textarea.value.split("\n").map(s => s.trim()).filter(Boolean);
    const seen = new Set();
    const cleaned = [];
    for (const item of raw) {
        const key = item.toLowerCase();
        if (!seen.has(key)) {
            seen.add(key);
            cleaned.push(item);
        }
    }
    textarea.value = cleaned.join("\n");
    updateCandidatesCount();
    logConsole(`Cleaned list: ${cleaned.length} unique candidates.`, "info");
}

function clearMemberList() {
    document.getElementById("memberListTextarea").value = "";
    updateCandidatesCount();
}

function generateRandomKhmerPhones() {
    const prefixes = ["+85510", "+85511", "+85512", "+85517", "+85592", "+85593", "+85598"];
    const generated = [];
    for (let i = 0; i < 50; i++) {
        const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
        const suffix = Math.floor(100000 + Math.random() * 900000);
        generated.push(`${prefix}${suffix}`);
    }
    appendMembersToTextarea(generated);
    logConsole("Generated 50 random Cambodian phone numbers.", "info");
}

function handleTxtFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;
        const lines = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        appendMembersToTextarea(lines);
        logConsole(`Imported ${lines.length} lines from ${file.name}`, "success");
    };
    reader.readAsText(file);
}

// ==========================================
// Member Adding Engine
// ==========================================
async function startAddingMembers() {
    if (!getLicenseKey()) {
        openLicenseModal();
        return;
    }

    const targetGroup = document.getElementById("targetGroupInput").value.trim();
    const textarea = document.getElementById("memberListTextarea");
    const members = textarea.value.split("\n").map(s => s.trim()).filter(Boolean);
    const delay = parseFloat(document.getElementById("delaySlider").value) || 3.0;
    const maxPerAcc = parseInt(document.getElementById("maxAccSlider").value) || 30;

    if (!targetGroup) {
        alert(currentLanguage === "km" ? "សូមបញ្ចូលតំណភ្ជាប់ក្រុមគោលដៅ!" : "Please enter the target group link or username!");
        return;
    }

    if (members.length === 0) {
        alert(currentLanguage === "km" ? "សូមបញ្ចូលសមាជិកក្នុងបញ្ជីជាមុនសិន!" : "Please add candidates to the member list first!");
        return;
    }

    const activeAccounts = currentAccounts.filter(a => a.enabled && !a.spam_flagged && !a.needs_reauth);
    if (activeAccounts.length === 0) {
        const msg = currentLanguage === "km"
            ? "មិនមានគណនី Telegram សកម្ម ឬត្រូវបានអនុញ្ញាតទេ! សូមពិនិត្យមើលគណនី ឬចុច Re-login។"
            : "No active authorized Telegram accounts found! Please enable an account or re-login.";
        alert(msg);
        return;
    }

    const btnStart = document.getElementById("btnStartAdd");
    const btnStop = document.getElementById("btnStopAdd");

    btnStart.disabled = true;
    btnStop.disabled = false;
    isJobRunning = true;
    const pBar = document.getElementById("jobProgressBar");
    if (pBar) {
        pBar.classList.add("animate-stripes");
        pBar.style.width = "0%";
    }

    // Initialize UI counters
    document.getElementById("statAdded").innerText = "0";
    document.getElementById("statSkipped").innerText = "0";
    document.getElementById("statTotal").innerText = members.length;
    document.getElementById("jobProgressPercent").innerText = "0%";

    const breakdown = {};
    activeAccounts.forEach(a => {
        breakdown[a.phone_number] = { invites_done: 0, is_premium: !!a.is_premium, status: "ready" };
    });

    logConsole(`Initializing Telegram Adder for ${members.length} candidates -> ${targetGroup}`, "info");

    let addedCount = 0;
    let skippedCount = 0;
    let workerIdx = 0;

    for (let idx = 0; idx < members.length; idx++) {
        if (!isJobRunning) {
            logConsole("Process stopped by user.", "warning");
            document.getElementById("jobStatusText").innerText = "Stopped by user";
            break;
        }

        const candidate = members[idx];
        const progressVal = Math.round(((idx + 1) / members.length) * 100);

        // Pick available worker:
        // Premium accounts: unlimited invites!
        // Standard accounts: invites_done < maxPerAcc
        const availableWorkers = activeAccounts.filter(a => {
            const b = breakdown[a.phone_number];
            return !a.spam_flagged && !a.needs_reauth && b && b.status === "ready" && (a.is_premium || b.invites_done < maxPerAcc);
        });

        if (availableWorkers.length === 0) {
            logConsole("All accounts reached invite limits or were restricted.", "warning");
            document.getElementById("jobStatusText").innerText = "All accounts limited";
            break;
        }

        const worker = availableWorkers[workerIdx % availableWorkers.length];
        workerIdx++;
        const phone = worker.phone_number;
        const premTag = worker.is_premium ? " ⭐ Premium" : "";

        const statusText = `[${phone}${premTag}] Inviting ${candidate} (${idx + 1}/${members.length})...`;
        document.getElementById("jobStatusText").innerText = statusText;
        document.getElementById("jobProgressPercent").innerText = `${progressVal}%`;
        if (pBar) pBar.style.width = `${progressVal}%`;

        try {
            const res = await fetch(`${API_BASE}/api/members/invite-one`, {
                method: "POST",
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    target_group: targetGroup,
                    member: candidate,
                    account: worker,
                    accounts_override: currentAccounts
                })
            });
            const data = await res.json();

            if (res.ok && data.success && data.status === "added") {
                addedCount++;
                breakdown[phone].invites_done++;
                logConsole(data.message, "success");
            } else if (data.status === "peer_flood" || data.status === "flood_wait") {
                skippedCount++;
                breakdown[phone].status = "limited";
                worker.spam_flagged = true;
                const secs = data.seconds || 0;
                const waitLabel = secs > 60 ? `${Math.ceil(secs / 60)}m (${secs}s)` : `${secs}s`;
                logConsole(`⚠️ Account ${phone} hit Telegram Flood limit (${waitLabel}). Pausing worker.`, "warning");
                saveAccountsToLocalStorage(currentAccounts);
                renderAccounts(currentAccounts);

                // Check if any available workers remain
                const remainingWorkers = activeAccounts.filter(a => {
                    const b = breakdown[a.phone_number];
                    return !a.spam_flagged && !a.needs_reauth && b && b.status === "ready" && (a.is_premium || b.invites_done < maxPerAcc);
                });
                if (remainingWorkers.length === 0) {
                    const stopMsg = currentLanguage === "km"
                        ? `⚠️ គណនី Telegram ទាំងអស់បានជាប់ Flood Wait របស់ Telegram (${waitLabel})។ ប្រព័ន្ធបានផ្អាកដោយស្វ័យប្រវត្តិដើម្បីការពារគណនីរបស់អ្នក។`
                        : `⚠️ All accounts hit Telegram Flood Wait (${waitLabel}). Adder stopped automatically to protect your Telegram account.`;
                    logConsole(stopMsg, "error");
                    alert(stopMsg);
                    break;
                }
            } else if (data.status === "unauthorized" || data.status === "auth_key_duplicated") {
                skippedCount++;
                breakdown[phone].status = "unauthorized";
                worker.needs_reauth = true;
                saveAccountsToLocalStorage(currentAccounts);
                renderAccounts(currentAccounts);
                const alertMsg = currentLanguage === "km"
                    ? `⚠️ គណនី ${phone} ត្រូវបាន Telegram កាត់ផ្តាច់ (Session ផុតកំណត់ ឬប្រើលើ IP ផ្សេងគ្នា)។ សូមចុច Re-login គណនីនេះឡើងវិញ!`
                    : `⚠️ Account ${phone} session expired or revoked by Telegram. Please Re-login this account!`;
                logConsole(alertMsg, "error");
                alert(alertMsg);
                break;
            } else if (data.status === "connect_failed") {
                skippedCount++;
                breakdown[phone].status = "unauthorized";
                worker.needs_reauth = true;
                saveAccountsToLocalStorage(currentAccounts);
                renderAccounts(currentAccounts);
                const alertMsg = currentLanguage === "km"
                    ? `⚠️ មិនអាចតភ្ជាប់គណនី ${phone} បានទេ: ${data.message || 'សូមពិនិត្យមើលគណនី ឬ Re-login'}`
                    : `⚠️ Could not connect account ${phone}: ${data.message || 'Please check or re-login'}`;
                logConsole(alertMsg, "error");
                alert(alertMsg);
                break;
            } else if (data.status === "privacy_restricted") {
                skippedCount++;
                logConsole(data.message || `⚠️ Skipped ${candidate} (User privacy settings block stranger invites)`, "warning");
            } else if (data.status === "no_admin") {
                skippedCount++;
                breakdown[phone].status = "no_admin";
                logConsole(`⚠️ Account ${phone} requires admin permissions in target group.`, "error");
            } else if (data.status === "already_participant") {
                skippedCount++;
                logConsole(data.message || `${candidate} is already a member.`, "info");
            } else {
                skippedCount++;
                logConsole(data.message || `Skipped ${candidate}`, "warning");
            }
        } catch (err) {
            skippedCount++;
            logConsole(`Failed to invite ${candidate}: ${err.message}`, "error");
        }

        document.getElementById("statAdded").innerText = addedCount;
        document.getElementById("statSkipped").innerText = skippedCount;

        // Delay between invites (if not stopped and not last)
        if (idx < members.length - 1 && isJobRunning) {
            await new Promise(r => setTimeout(r, delay * 1000));
        }
    }

    isJobRunning = false;
    btnStart.disabled = false;
    btnStop.disabled = true;
    if (pBar) {
        pBar.classList.remove("animate-stripes");
        pBar.style.width = "100%";
    }
    document.getElementById("jobProgressPercent").innerText = "100%";
    logConsole(`Adding finished! Added: ${addedCount}, Skipped/Failed: ${skippedCount}`, "success");

    // Open summary modal with real numbers
    openSummaryModal(addedCount, skippedCount, breakdown);
}

async function stopAddingMembers() {
    isJobRunning = false;
    const pBar = document.getElementById("jobProgressBar");
    if (pBar) pBar.classList.remove("animate-stripes");
    const btnStop = document.getElementById("btnStopAdd");
    if (btnStop) {
        btnStop.disabled = true;
        btnStop.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Stopping...`;
    }
    logConsole("Stop request sent. Stopping adder...", "warning");
    setTimeout(() => {
        if (btnStop) {
            btnStop.innerHTML = `<i class="fas fa-stop"></i> <span id="btnStopText">${I18N[currentLanguage].btnStopText}</span>`;
        }
    }, 1000);
}

// ==========================================
// WebSocket Real-Time Events & Fallback Polling
// ==========================================
let jobStatusPoller = null;

function initWebSocket() {
    const hostname = window.location.hostname || "";
    // Only Vercel serverless lacks WebSocket support entirely
    const isVercel = hostname.endsWith(".vercel.app");
    if (isVercel) {
        startJobStatusFallbackPoller();
        return;
    }

    let wsUrl;
    if (API_BASE) {
        wsUrl = API_BASE.replace(/^http/, "ws") + "/ws/events";
    } else {
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        wsUrl = `${protocol}//${location.host}/ws/events`;
    }
    try {
        websocket = new WebSocket(wsUrl);
    } catch (e) {
        startJobStatusFallbackPoller();
        return;
    }

    websocket.onopen = () => {
        wsEverOpened = true;
        if (jobStatusPoller) {
            clearInterval(jobStatusPoller);
            jobStatusPoller = null;
        }
    };

    websocket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        } catch (e) {
            console.error(e);
        }
    };

    websocket.onclose = () => {
        // Fallback polling if WebSocket closes or fails
        if (isJobRunning && !jobStatusPoller) {
            startJobStatusFallbackPoller();
        }
        if (wsEverOpened) {
            setTimeout(initWebSocket, 2500);
        }
    };

    websocket.onerror = () => {
        if (!wsEverOpened) {
            startJobStatusFallbackPoller();
        }
    };
}

function startJobStatusFallbackPoller() {
    if (jobStatusPoller) return;
    jobStatusPoller = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/members/status`, {
                headers: getAuthHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                if (data && data.job) {
                    const job = data.job;
                    if (job.is_running) {
                        isJobRunning = true;
                        handleWsMessage({
                            type: "progress",
                            progress: job.progress || 0,
                            status: job.status_message || "",
                            added: job.added_count || 0,
                            skipped: job.skipped_count || 0,
                            total: job.total_count || 0,
                        });
                    }
                }
            }
        } catch (e) {
            // ignore network glitch
        }
    }, 3000);
}

function handleWsMessage(msg) {
    if (msg.type === "log" && msg.data) {
        logConsole(msg.data.msg, msg.data.level, msg.data.time);
    }

    if (msg.type === "progress") {
        document.getElementById("jobProgressPercent").innerText = `${msg.progress ?? 0}%`;
        const pb = document.getElementById("jobProgressBar");
        pb.style.width = `${msg.progress ?? 0}%`;
        pb.classList.add("animate-stripes");
        document.getElementById("jobStatusText").innerText = msg.status || "";
        document.getElementById("statAdded").innerText = msg.added ?? 0;
        document.getElementById("statSkipped").innerText = msg.skipped ?? 0;
        document.getElementById("statTotal").innerText = msg.total ?? 0;
    }

    if (msg.type === "finished") {
        isJobRunning = false;
        document.getElementById("btnStartAdd").disabled = false;
        document.getElementById("btnStopAdd").disabled = true;
        document.getElementById("jobProgressPercent").innerText = "100%";
        const pb = document.getElementById("jobProgressBar");
        pb.style.width = "100%";
        pb.classList.remove("animate-stripes");

        const added = msg.added ?? 0;
        const skipped = msg.skipped ?? 0;
        const breakdown = msg.breakdown || {};
        openSummaryModal(added, skipped, breakdown);
    }

    if (msg.type === "init" && msg.job) {
        const job = msg.job;
        if (job.is_running) {
            isJobRunning = true;
            document.getElementById("btnStartAdd").disabled = true;
            document.getElementById("btnStopAdd").disabled = false;
            document.getElementById("jobProgressPercent").innerText = `${job.progress ?? 0}%`;
            const pb = document.getElementById("jobProgressBar");
            pb.style.width = `${job.progress ?? 0}%`;
            pb.classList.add("animate-stripes");
            document.getElementById("jobStatusText").innerText = job.status_message || "";
            document.getElementById("statAdded").innerText = job.added_count ?? 0;
            document.getElementById("statSkipped").innerText = job.skipped_count ?? 0;
            document.getElementById("statTotal").innerText = job.total_count ?? 0;
        }
    }
}

function logConsole(msg, level = "info", timestamp = null) {
    const consoleArea = document.getElementById("consoleLogArea");
    if (!consoleArea) return;

    const time = timestamp || new Date().toLocaleTimeString();
    let colorClass = "text-gray-300";
    let badgeClass = "text-cyan-400";

    if (level === "success") {
        colorClass = "text-emerald-300";
        badgeClass = "text-emerald-400";
    } else if (level === "warning") {
        colorClass = "text-yellow-300";
        badgeClass = "text-yellow-400";
    } else if (level === "error") {
        colorClass = "text-red-400 font-semibold";
        badgeClass = "text-red-400";
    }

    const logItem = document.createElement("div");
    logItem.className = `flex items-start gap-1.5 ${colorClass}`;
    logItem.innerHTML = `
        <span class="text-gray-600 shrink-0 font-mono">[${time}]</span>
        <span class="shrink-0 font-bold ${badgeClass}">›</span>
        <span class="break-all">${msg}</span>
    `;

    consoleArea.appendChild(logItem);
    consoleArea.scrollTop = consoleArea.scrollHeight;
}

function clearConsoleLogs() {
    const consoleArea = document.getElementById("consoleLogArea");
    if (consoleArea) {
        consoleArea.innerHTML = '<div class="text-gray-600">[Console cleared]</div>';
    }
}

// ==========================================
// Summary Modal
// ==========================================
function openSummaryModal(added, skipped, breakdown = {}) {
    document.getElementById("sumTotalAdded").innerText = added;
    document.getElementById("sumTotalSkipped").innerText = skipped;

    const listEl = document.getElementById("sumBreakdownList");
    const entries = Object.entries(breakdown);

    if (entries.length === 0) {
        listEl.innerHTML = '<span class="text-gray-500">No account breakdown recorded.</span>';
    } else {
        listEl.innerHTML = entries.map(([phone, data]) => {
            const prem = data.is_premium ? '⭐ Premium' : 'Standard';
            const isSpam = data.status && (data.status === 'limited' || data.status.startsWith('flood_wait'));
            const statusNote = data.status && data.status !== 'ready'
                ? ` <span class="${isSpam ? 'text-red-400' : 'text-yellow-400'}">(${data.status})</span>`
                : '';
            const spamTag = isSpam
                ? `<span class="ml-1 px-1 py-0.5 rounded text-[9px] font-bold bg-red-500/20 text-red-400 border border-red-500/40">⚠️ Spam</span>`
                : '';
            return `
                <div class="flex justify-between items-center text-xs py-1 border-b border-gray-800">
                    <span class="font-mono ${isSpam ? 'text-red-300' : 'text-gray-300'}">${phone} <span class="text-gray-500">(${prem})</span>${spamTag}</span>
                    <span class="font-bold text-cyan-400">${data.invites_done} added${statusNote}</span>
                </div>
            `;
        }).join("");
    }

    document.getElementById("summaryModal").classList.remove("hidden");
}

function closeSummaryModal() {
    document.getElementById("summaryModal").classList.add("hidden");
}

// ==========================================
// System Stats Poller
// ==========================================
function startSystemStatsPoller() {
    async function updateStats() {
        try {
            const res = await fetch(`${API_BASE}/api/system/stats`);
            const data = await res.json();
            if (data && !data.error) {
                document.getElementById("statCpu").innerText = `${data.cpu_percent}%`;
                document.getElementById("statRam").innerText = `${data.ram_used_gb}/${data.ram_total_gb} GB (${data.ram_percent}%)`;
                document.getElementById("statDisk").innerText = `${data.disk_free_gb} GB free`;
            }
        } catch (e) {
            // ignore
        }
    }
    updateStats();
    setInterval(updateStats, 3500);
}

