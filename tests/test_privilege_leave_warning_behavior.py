import json
import subprocess
from pathlib import Path


def test_privilege_leave_warning_confirm_paths():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "script.js"

    node_script = """
const fs = require('fs');
const code = fs.readFileSync(__SCRIPT_PATH__, 'utf8');

const originalLog = console.log;
console.log = () => {};

let nextWarningResponse = false;
const warningCalls = [];

function createClassList() {
  return {
    add() {},
    remove() {},
  };
}

class RadioInput {
  constructor(value) {
    this.value = value;
    this.name = 'leaveType';
    this.type = 'radio';
    this._checked = false;
    this._peers = null;
    this.dataset = {};
    this.style = {};
    this.classList = createClassList();
    this.listeners = {};
  }

  set checked(value) {
    const isChecked = Boolean(value);
    if (this._checked === isChecked) {
      this._checked = isChecked;
      return;
    }
    this._checked = isChecked;
    if (isChecked && Array.isArray(this._peers)) {
      this._peers.forEach(peer => {
        if (peer !== this) {
          peer._checked = false;
        }
      });
    }
  }

  get checked() {
    return this._checked;
  }

  setPeers(peers) {
    this._peers = peers;
  }

  addEventListener(event, handler) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(handler);
  }
}

global.window = global;
window.location = { href: 'http://localhost/', search: '' };
window.addEventListener = () => {};
window.eval = eval;
window.confirm = () => {
  warningCalls.push(nextWarningResponse);
  return nextWarningResponse;
};
window.alert = () => {};

const radios = [
  new RadioInput('vacation-leave'),
  new RadioInput('leave-without-pay'),
];
radios.forEach(radio => radio.setPeers(radios));
radios[0].checked = true;

const elementsById = new Map([
  ['reason', { disabled: false }],
  ['reasonNote', { textContent: '' }],
  ['durationText', { textContent: '' }],
  ['startDate', { value: '2024-01-01' }],
  ['endDate', { value: '2024-01-01' }],
  ['startTime', { value: '07:30', dataset: {}, classList: createClassList() }],
  ['endTime', { value: '14:30', dataset: {}, classList: createClassList() }],
  ['loadingOverlay', { classList: createClassList() }],
]);

global.document = {
  getElementById(id) {
    if (elementsById.has(id)) {
      return elementsById.get(id);
    }
    const created = { dataset: {}, classList: createClassList(), style: {} };
    elementsById.set(id, created);
    return created;
  },
  querySelectorAll(selector) {
    if (selector === 'input[name="leaveType"]') {
      return radios;
    }
    return [];
  },
  querySelector(selector) {
    if (selector === 'input[name="leaveType"]:checked') {
      return radios.find(radio => radio.checked) || null;
    }
    return null;
  },
  addEventListener: () => {},
  createElement: tag => ({ tagName: tag, classList: createClassList(), dataset: {}, style: {} }),
};

global.navigator = { userAgent: 'node' };
global.sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

global.fetch = async () => ({ ok: true, json: async () => ({}), text: async () => '' });

global.FormData = class {
  constructor(target) {
    this.target = target;
  }

  get(name) {
    if (typeof this.target.getFormValue === 'function') {
      return this.target.getFormValue(name);
    }
    return this.target[name] ?? null;
  }
};

eval(code);

const LEAVE_WITHOUT_PAY_VALUE_CONST = 'leave-without-pay';

window.eval('(() => { currentPrivilegeRemainingDays = 5; })();');
window.eval('(() => { lastValidLeaveTypeValue = "vacation-leave"; })();');
window.eval('canCoverWithPrivilegeLeave = () => true;');

window.submitLeaveApplicationForTest = async function(event) {
  event.preventDefault();
  showLoading();
  const formData = new FormData(event.target);
  const selectedLeaveType = formData.get('leaveType');

  if (selectedLeaveType === LEAVE_WITHOUT_PAY_VALUE_CONST && canCoverWithPrivilegeLeave()) {
    hideLoading();
    const proceed = showPrivilegeLeaveWarning();
    if (!proceed) {
      revertLeaveWithoutPaySelection();
      updateLeaveReasonState();
      return;
    }
    showLoading();
  }

  await room.collection('leave_application').create({
    leave_type: selectedLeaveType,
    employee_id: 'emp-1',
  });

  hideLoading();
};

setupLeaveTypeHandling();

const leaveWithoutPayRadio = radios[1];
const vacationRadio = radios[0];
const changeHandlers = leaveWithoutPayRadio.listeners.change || [];
if (!changeHandlers.length) {
  throw new Error('Expected change handler to be registered');
}
const changeHandler = changeHandlers[0];

const results = {};

nextWarningResponse = false;
leaveWithoutPayRadio.checked = true;
changeHandler.call(leaveWithoutPayRadio);
results.cancelSelection = {
  leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
  vacationChecked: vacationRadio.checked,
};

nextWarningResponse = true;
window.eval('(() => { lastValidLeaveTypeValue = "vacation-leave"; })();');
leaveWithoutPayRadio.checked = true;
changeHandler.call(leaveWithoutPayRadio);
results.confirmSelection = {
  leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
  vacationChecked: vacationRadio.checked,
};

const formValues = {
  startDate: '2024-01-01',
  endDate: '2024-01-01',
  startTime: '07:30',
  endTime: '14:30',
  reason: 'Testing',
};

const formTarget = {
  getFormValue(name) {
    if (name === 'leaveType') {
      const selected = radios.find(radio => radio.checked);
      return selected ? selected.value : null;
    }
    return Object.prototype.hasOwnProperty.call(formValues, name) ? formValues[name] : null;
  },
};

let createCallCount = 0;
let lastPayload = null;

room.collection = function(name) {
  return {
    create: async data => {
      createCallCount += 1;
      lastPayload = { name, data };
      return { id: 'created-id' };
    },
  };
};

const event = {
  preventDefault() {},
  target: formTarget,
};

async function runSubmissionSequence() {
  nextWarningResponse = false;
  window.eval('(() => { lastValidLeaveTypeValue = "vacation-leave"; })();');
  leaveWithoutPayRadio.checked = true;
  await submitLeaveApplicationForTest(event);
  results.cancelSubmission = {
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    createCallCount,
  };

  nextWarningResponse = true;
  window.eval('(() => { lastValidLeaveTypeValue = "vacation-leave"; })();');
  leaveWithoutPayRadio.checked = true;
  await submitLeaveApplicationForTest(event);
  results.confirmSubmission = {
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    createCallCount,
    payloadLeaveType: lastPayload ? lastPayload.data.leave_type : null,
  };
}

runSubmissionSequence().then(() => {
  console.log = originalLog;
  results.warningCalls = warningCalls;
  console.log(JSON.stringify(results));
}).catch(error => {
  console.log = originalLog;
  console.error(error);
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

    cancel_selection = result["cancelSelection"]
    assert cancel_selection["leaveWithoutPayChecked"] is False
    assert cancel_selection["vacationChecked"] is True

    confirm_selection = result["confirmSelection"]
    assert confirm_selection["leaveWithoutPayChecked"] is True
    assert confirm_selection["vacationChecked"] is False

    cancel_submission = result["cancelSubmission"]
    assert cancel_submission["leaveWithoutPayChecked"] is False
    assert cancel_submission["vacationChecked"] is True
    assert cancel_submission["createCallCount"] == 0

    confirm_submission = result["confirmSubmission"]
    assert confirm_submission["leaveWithoutPayChecked"] is True
    assert confirm_submission["vacationChecked"] is False
    assert confirm_submission["createCallCount"] == 1
    assert confirm_submission["payloadLeaveType"] == "leave-without-pay"

    assert result["warningCalls"] == [False, True, False, True]
