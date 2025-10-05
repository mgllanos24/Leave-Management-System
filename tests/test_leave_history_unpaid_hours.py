import json
import subprocess
from pathlib import Path


def test_leave_history_renders_unpaid_hours_when_paid_is_less_than_total():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "script.js"

    node_script = """
const fs = require('fs');
const code = fs.readFileSync(__SCRIPT_PATH__, 'utf8');
const originalLog = console.log;
console.log = () => {};

global.window = global;
window.location = { href: 'http://localhost/', search: '' };
window.addEventListener = () => {};

function createClassList() {
  return { add() {}, remove() {} };
}

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this._innerHTML = '';
    this.attributes = {};
    this.classList = createClassList();
    this.style = {};
    this.dataset = {};
    this.value = '';
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
    if (this.appended) {
      this.appended = [];
    }
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    this.children.push(child);
  }

  querySelectorAll() {
    return [];
  }

  querySelector() {
    return null;
  }

  addEventListener() {}

  removeEventListener() {}

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  get textContent() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._innerHTML = value;
  }
}

const tbody = new Element('tbody');
tbody.appended = [];
const originalAppendChild = tbody.appendChild.bind(tbody);
tbody.appendChild = child => {
  originalAppendChild(child);
  tbody.appended.push(child);
};

const leaveBalanceDisplay = new Element('div');
leaveBalanceDisplay.style.display = 'none';
const privilegeBalance = new Element('span');
const sickBalance = new Element('span');

const elementsById = {
  employeeHistoryTableBody: tbody,
  leaveBalanceDisplay,
  privilegeLeaveBalance: privilegeBalance,
  sickLeaveBalance: sickBalance,
};

global.document = {
  createElement: tag => new Element(tag),
  getElementById: id => elementsById[id] || new Element('div'),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
};

document.body = new Element('body');

global.alert = () => {};
global.confirm = () => true;
const leaveBalances = [
  { balance_type: 'PRIVILEGE', remaining_days: '4', year: 2022 },
  { balance_type: 'PRIVILEGE', remaining_days: '5', year: 2023 },
  { balance_type: 'PRIVILEGE', remaining_days: '7', year: new Date().getFullYear() },
  { balance_type: 'SICK', remaining_days: '10', year: new Date().getFullYear() },
];

const fetchCalls = [];
global.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};
global.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};
global.AbortController = class {
  constructor() {
    this.signal = {};
  }

  abort() {}
};
global.FormData = class {
  constructor() {}
  append() {}
};
global.File = class {};
global.navigator = { userAgent: 'node' };

eval(code);
console.log = originalLog;

window.__fetchCalls = fetchCalls;
window.eval(`
  fetch = async (...args) => {
    window.__fetchCalls.push(args);
    const [url] = args;
    if (typeof url === 'string' && url.startsWith('/api/leave_balance')) {
      return {
        ok: true,
        json: async () => ${JSON.stringify(leaveBalances)},
        text: async () => ${JSON.stringify(leaveBalances)},
      };
    }
    return { ok: true, json: async () => ({}), text: async () => '' };
  };
`);
global.fetch = (...args) => window.fetch(...args);

window.eval(`
  const __testBalances = ${JSON.stringify(leaveBalances)};
  updateLeaveBalanceDisplay = async function() {
    const container = document.getElementById('leaveBalanceDisplay');
    if (!currentUser || !container) {
      currentVacationRemainingDays = 0;
      return;
    }
    const balances = __testBalances;
    const currentYear = new Date().getFullYear();
    const selectMostRelevantBalance = (entries) => {
      if (!entries || entries.length === 0) {
        return null;
      }
      const withYear = entries.map(entry => ({ entry, year: Number.parseInt(entry.year, 10) }));
      const exactMatch = withYear.find(item => item.year === currentYear);
      if (exactMatch) {
        return exactMatch.entry;
      }
      let mostRecent = null;
      for (const item of withYear) {
        if (!Number.isFinite(item.year)) {
          continue;
        }
        if (!mostRecent || item.year > mostRecent.year) {
          mostRecent = item;
        }
      }
      if (mostRecent) {
        return mostRecent.entry;
      }
      return entries[0];
    };

    const privilegeBalances = balances.filter(b => b.balance_type === 'PRIVILEGE');
    const priv = selectMostRelevantBalance(privilegeBalances);
    const sick = balances.find(b => b.balance_type === 'SICK');

    const parsedPrivilege = priv && priv.remaining_days != null
      ? Number.parseFloat(priv.remaining_days)
      : 0;
    currentVacationRemainingDays = Number.isFinite(parsedPrivilege) ? parsedPrivilege : 0;

    const privEl = document.getElementById('privilegeLeaveBalance');
    const sickEl = document.getElementById('sickLeaveBalance');
    if (privEl) {
      if (priv && priv.remaining_days != null) {
        privEl.textContent = priv.remaining_days + ' days';
        if (priv.year != null) {
          privEl.dataset.year = priv.year;
        } else if (privEl.dataset && privEl.dataset.year) {
          delete privEl.dataset.year;
        }
      } else {
        privEl.textContent = '-- days';
        if (privEl.dataset && privEl.dataset.year) {
          delete privEl.dataset.year;
        }
      }
    }
    if (sickEl) {
      sickEl.textContent = sick && sick.remaining_days != null
        ? sick.remaining_days + ' days'
        : '-- days';
    }

    container.style.display = 'block';
  };
`);

const backendRoom = window.room;

const applications = [
  {
    id: '101',
    application_id: 'APP-101',
    total_hours: 56,
    start_date: '2024-03-01',
    end_date: '2024-03-07',
    start_time: '08:00',
    end_time: '17:00',
    leave_type: 'Leave Without Pay',
    status: 'Approved',
  },
];

const balanceHistory = [
  {
    employee_id: 'emp-1',
    application_id: '101',
    change_type: 'DEDUCTION',
    balance_type: 'PRIVILEGE',
    change_amount: 5,
    previous_balance: 5,
    new_balance: 0,
  },
  {
    employee_id: 'emp-1',
    application_id: '101',
    change_type: 'UNPAID',
    balance_type: 'PRIVILEGE',
    change_amount: 2,
    previous_balance: 0,
    new_balance: 0,
  },
];

backendRoom.collection = name => ({
  makeRequest() {
    if (name === 'leave_application') return Promise.resolve(applications);
    if (name === 'leave_balance_history') return Promise.resolve(balanceHistory);
    return Promise.resolve([]);
  },
  getList() {
    return this.makeRequest('GET');
  },
});

(async () => {
  try {
    currentUser = { id: 'emp-1' };
  } catch (error) {
    globalThis.currentUser = { id: 'emp-1' };
  }
  if (!currentUser || currentUser.id !== 'emp-1') {
    window.eval("currentUser = { id: 'emp-1' }");
  }
  await loadLeaveHistory('emp-1');
  if (!tbody.appended.length) {
    throw new Error('Expected at least one row to be rendered');
  }
  const firstRow = tbody.appended[0];
  const cells = firstRow.innerHTML
    .split('</td>')
    .filter(Boolean)
    .map(segment => segment.replace(/^.*?>/s, '').trim());

  await updateLeaveBalanceDisplay();

  const result = {
    cellCount: cells.length,
    leaveLabel: cells[1] || null,
    paidCell: cells[5] || null,
    unpaidCell: cells[6] || null,
    privilegeBalance: privilegeBalance.textContent,
    privilegeYear: privilegeBalance.dataset.year,
    leaveBalanceDisplay: leaveBalanceDisplay.style.display,
  };

  originalLog(JSON.stringify(result));
})().catch(error => {
  originalLog(JSON.stringify({ error: error.message }));
  process.exit(1);
});
"""

    node_script = node_script.replace("__SCRIPT_PATH__", json.dumps(str(script_path)))

    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )

    output = completed.stdout.strip()
    assert output, completed.stderr

    result = json.loads(output)
    assert result.get("cellCount") >= 8
    assert result.get("leaveLabel") == "Unpaid Leave"
    assert result.get("paidCell") == "40.00 h"
    assert result.get("unpaidCell") == "16.00 h"
    current_year = str(__import__("datetime").datetime.now().year)
    assert result.get("privilegeBalance") == "7 days"
    assert str(result.get("privilegeYear")) == current_year
    assert result.get("leaveBalanceDisplay") == "block"
