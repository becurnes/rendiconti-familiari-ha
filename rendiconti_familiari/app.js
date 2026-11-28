"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const moneyFormat = new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" });
const monthFormat = new Intl.DateTimeFormat("it-IT", { month: "long", year: "numeric" });
const dateFormat = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" });
const today = () => {
  const pieces = new Intl.DateTimeFormat("it-IT", {
    timeZone: "Europe/Rome", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts();
  const part = name => pieces.find(piece => piece.type === name).value;
  return [part("year"), part("month"), part("day")].join("-");
};
const money = cents => moneyFormat.format(cents / 100);
const dayLabel = day => dateFormat.format(new Date(day + "T12:00:00"));
const monthLabel = month => monthFormat.format(new Date(month + "-01T12:00:00"));
const monthInput = $("#month");
const editor = $("#editor");
const entryForm = $("#entry-form");
const peopleDialog = $("#people-dialog");
const bankDialog = $("#bank-dialog");
const printDialog = $("#print-dialog");
const createActions = ["#new-expense", "#new-payment", "#bank-open", "#people-open", "#print-open"];
let month = today().slice(0, 7);
let data = { people: [], expenses: [], payments: [], credits: [], months: [], arrears: [] };
let loadVersion = 0;
let entry = null;
let personID = null;
let bankRows = [];
let bankPreview = null;
let bankVersion = 0;
let bankSaving = false;
let allocationVersion = 0;
let allocationRows = [];

function element(tag, value, className) {
  const item = document.createElement(tag);
  if (value !== undefined) item.textContent = value;
  if (className) item.className = className;
  return item;
}

function button(label, action, className = "plain") {
  const item = element("button", label, className);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

function option(value, label) {
  return new Option(label, value);
}

async function api(endpoint, payload) {
  const settings = payload === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Rendiconti": "1" },
    body: JSON.stringify(payload),
  };
  const response = await fetch("./api/" + endpoint, { ...settings, cache: "no-store" });
  if (!(response.headers.get("Content-Type") || "").includes("application/json")) {
    throw new Error("Il sito non risponde. Riaprilo da Home Assistant.");
  }
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error || "Operazione non riuscita.");
  }
  return body;
}

function showMessage(item, message) {
  item.textContent = message;
  item.hidden = !message;
}

function total(items) {
  return items.reduce((sum, item) => sum + item.cents, 0);
}

function personName(id) {
  return data.people.find(person => person.id === id)?.name || "";
}

function summarize(personID) {
  const shares = data.expenses.flatMap(expense => expense.shares).filter(share => share.person_id === personID);
  const payments = data.credits.filter(payment => payment.person_id === personID);
  const owed = total(shares);
  const received = total(payments);
  return { owed, received, balance: owed - received };
}

function balanceLabel(balance) {
  if (balance < 0) return "Eccedenza";
  return "Residuo";
}

function field(parent, label, value, className) {
  const row = element("div", undefined, className);
  row.append(element("dt", label), element("dd", value));
  parent.append(row);
}

function record(heading, subtitle, value, edit, actionLabel = "Modifica") {
  const item = element("li");
  const detail = element("div", undefined, "record-detail");
  detail.append(element("strong", heading), element("span", subtitle, "hint"));
  const actions = element("div", undefined, "record-action");
  actions.append(element("strong", value), button(actionLabel, edit));
  item.append(detail, actions);
  return item;
}

function draw() {
  $("#period").textContent = monthLabel(month);
  monthInput.value = month;
  $("#history").replaceChildren(option("", "Archivio"),
    ...data.months.map(value => option(value, monthLabel(value))));
  const owed = total(data.expenses);
  const received = total(data.credits);
  const summaries = data.people.map(person => ({ ...person, ...summarize(person.id) }));
  const remaining = summaries.reduce((sum, person) => sum + Math.max(person.balance, 0), 0);
  const arrears = total(data.arrears);
  const totals = element("dl");
  field(totals, "Spese anticipate", money(owed));
  field(totals, "Versato sul mese", money(received));
  field(totals, "Residuo del mese", money(remaining));
  field(totals, "Arretrati", money(arrears));
  field(totals, "Totale da ricevere", money(remaining + arrears), "highlight");
  $("#totals").replaceChildren(totals);

  $("#balances").replaceChildren(...summaries.map(person => {
    const past = total(data.arrears.filter(item => item.person_id === person.id));
    const row = element("tr");
    const name = element("th", person.name);
    name.scope = "row";
    const action = element("td");
    action.append(button("Registra versamento", () => openEntry("payment", { person_id: person.id })));
    row.append(name, element("td", money(person.owed)), element("td", money(person.received)),
      element("td", person.balance < 0 ? money(-person.balance) + " di eccedenza" : money(person.balance)),
      element("td", money(past)), element("td", money(Math.max(person.balance, 0) + past), "balance-due"), action);
    return row;
  }));
  $("#arrears").hidden = !data.arrears.length;
  $("#arrears-list").replaceChildren(...data.arrears.map(item => {
    const row = record(personName(item.person_id), monthLabel(item.month), money(item.cents),
      () => openEntry("payment", { person_id: item.person_id, cents: item.cents, arrears_target: item.month }), "Registra versamento");
    $(".record-action", row).append(button("Apri mese", () => setMonth(item.month)));
    return row;
  }));
  $("#expenses").replaceChildren(...(data.expenses.length ? data.expenses.map(expense =>
    record(expense.description, [
      dayLabel(expense.day),
      ...expense.shares.map(share => personName(share.person_id) + " " + money(share.cents)),
    ].join(" · "), money(expense.cents), () => openEntry("expense", expense)))
    : [element("li", "Nessuna spesa in questo mese.", "empty")]));
  $("#payments").replaceChildren(...(data.payments.length ? data.payments.map(payment =>
    record(personName(payment.person_id), [
      dayLabel(payment.day), payment.note, ...payment.allocations.map(part =>
        "Saldo " + monthLabel(part.month) + " " + money(part.cents)),
    ].filter(Boolean).join(" · "), money(payment.cents), () => openEntry("payment", payment)))
    : [element("li", "Nessun versamento in questo mese.", "empty")]));
  const laterCredits = data.credits.filter(credit => credit.recorded_month !== month);
  $("#later-payments-heading").hidden = $("#later-payments").hidden = !laterCredits.length;
  $("#later-payments").replaceChildren(...laterCredits.map(credit =>
    record(personName(credit.person_id), [dayLabel(credit.day), credit.note].filter(Boolean).join(" · "),
      money(credit.cents), () => setMonth(credit.recorded_month), "Apri versamento")));

}

async function refresh() {
  const version = ++loadVersion;
  createActions.forEach(selector => { $(selector).disabled = true; });
  try {
    const fresh = await api("month?month=" + encodeURIComponent(month));
    if (version !== loadVersion) return false;
    data = fresh;
    draw();
    createActions.forEach(selector => { $(selector).disabled = false; });
    return true;
  } catch (error) {
    if (version === loadVersion) {
      showMessage($("#notice"), error.message);
    }
    return false;
  }
}

function setMonth(value) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value) || value.startsWith("0000")) return;
  month = value;
  $("#period").textContent = monthLabel(month);
  monthInput.value = month;
  showMessage($("#notice"), "");
  refresh();
}

function moveMonth(change) {
  const [year, part] = month.split("-").map(Number);
  const index = year * 12 + part - 1 + change;
  const value = Math.floor(index / 12).toString().padStart(4, "0") + "-" +
    (index % 12 + 1).toString().padStart(2, "0");
  setMonth(value);
}

function openEntry(kind, item = {}) {
  entry = { kind, item };
  const form = entryForm.elements;
  const expense = kind === "expense";
  const target = month;
  $("#entry-title").textContent = expense ? (item.id ? "Modifica spesa" : "Aggiungi spesa")
    : (item.id ? "Modifica versamento" : "Registra versamento");
  $("#entry-day-label span").textContent = expense ? "Data della spesa" : "Data del versamento";
  $("#entry-text-label span").textContent = expense ? "Descrizione" : "Nota (facoltativa)";
  form.month.value = target;
  form.day.value = item.day || (expense && month !== today().slice(0, 7) ? month + "-01" : today());
  form.amount.value = item.cents && item.cents <= 99999999
    ? (item.cents / 100).toFixed(2).replace(".", ",") : "";
  form.description.value = expense ? item.description || "" : item.note || "";
  form.description.required = expense;
  $("#share-field").hidden = !expense;
  $("#payment-person").hidden = expense;
  const selected = item.shares?.map(share => share.person_id) || [1, 2];
  $("#share-options").replaceChildren(...data.people.map(person => {
    const label = element("label", undefined, "choice");
    const check = element("input");
    Object.assign(check, { type: "checkbox", name: "share", value: person.id, checked: selected.includes(person.id) });
    label.append(check, document.createTextNode(person.name));
    return label;
  }));
  form.person.replaceChildren(...data.people.map(person => option(person.id, person.name)));
  if (item.person_id) form.person.value = item.person_id;
  $("#entry-delete").hidden = !item.id;
  showMessage($(".form-error", entryForm), "");
  $("#payment-destination").hidden = true;
  form.arrears_target.required = false;
  form.arrears_target.replaceChildren(option("current", "Mese del versamento"));
  editor.showModal();
  if (!expense) loadAllocationChoices(item.arrears_target || (item.id ? "current" : ""));
}

function drawAllocationNote() {
  const { person, arrears_target, amount } = entryForm.elements;
  const applicable = allocationRows.filter(row => row.person_id === Number(person.value) &&
    (arrears_target.value === "all" || row.month === arrears_target.value));
  let description = "";
  if (arrears_target.value && applicable.length) {
    try {
      const cents = parseCents(amount.value);
      const excess = cents - total(applicable);
      const oldest = applicable[0];
      description = arrears_target.value === "all"
        ? "Il versamento parte da " + monthLabel(oldest.month) + ". " : "";
      if (excess > 0) description += money(excess) + " resta imputato al mese del versamento.";
    } catch {
      if (arrears_target.value === "all") description = "Si parte dal mese meno recente.";
    }
  }
  showMessage($("#allocation-note"), description);
}

async function loadAllocationChoices(preferred = entryForm.elements.arrears_target.value) {
  const version = ++allocationVersion;
  const { month: period, person, arrears_target: allocation } = entryForm.elements;
  const submit = $('button[type="submit"]', entryForm);
  const item = entry.item;
  allocationRows = [];
  if (!period.value) return;
  submit.disabled = true;
  showMessage($(".form-error", entryForm), "");
  try {
    const useDisplayedMonth = period.value === month && !item.id;
    const balances = useDisplayedMonth ? data.arrears : await api("arrears?month=" +
      encodeURIComponent(period.value) + (item.id ? "&exclude=" + item.id : ""));
    if (version !== allocationVersion || !editor.open) return;
    allocationRows = balances;
    const matching = allocationRows.filter(row => row.person_id === Number(person.value));
    const choices = [option("current", "Mese del versamento")];
    if (matching.length) {
      choices.push(option("all", "Arretrati, dal mese più vecchio (" + money(total(matching)) + ")"));
      choices.push(...matching.map(row => option(row.month, monthLabel(row.month) + " (" + money(row.cents) + ")")));
    }
    const unchangedTarget = preferred && preferred === item.arrears_target &&
      Number(person.value) === item.person_id && period.value === month;
    if (unchangedTarget && !choices.some(choice => choice.value === preferred)) {
      choices.push(option(preferred, "Imputazione già registrata"));
    }
    const hasChoice = choices.length > 1;
    allocation.required = hasChoice;
    if (hasChoice) choices.unshift(option("", "Scegli la destinazione"));
    allocation.replaceChildren(...choices);
    allocation.value = choices.some(choice => choice.value === preferred) ? preferred : choices[0].value;
    $("#payment-destination").hidden = !hasChoice;
    drawAllocationNote();
  } catch (error) {
    if (version !== allocationVersion || !editor.open) return;
    showMessage($(".form-error", entryForm), "Impossibile verificare gli arretrati. " + error.message);
    return;

  }
  if (version === allocationVersion) submit.disabled = false;
}

function parseCents(value) {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d{1,6}(\.\d{1,2})?$/.test(normalized)) throw new Error("Inserisci un importo valido, ad esempio 24,50.");
  const [euros, cents = ""] = normalized.split(".");
  const amount = Number(euros) * 100 + Number(cents.padEnd(2, "0"));
  if (amount < 1) throw new Error("Inserisci un importo maggiore di zero.");
  return amount;
}

async function submitEntry(event) {
  event.preventDefault();
  const submit = $('button[type="submit"]', entryForm);
  if (submit.disabled) return;
  submit.disabled = true;
  const active = entry;
  try {
    const fields = entryForm.elements;
    const target = { id: active.item.id, month: fields.month.value,
      day: fields.day.value, cents: parseCents(fields.amount.value) };
    if (active.kind === "expense") {
      target.description = fields.description.value;
      target.source_key = active.item.key;
      target.people = Array.from(entryForm.querySelectorAll("input[name=share]:checked"), input => Number(input.value));
    } else {
      target.note = fields.description.value;
      target.person_id = Number(fields.person.value);
      target.arrears_target = fields.arrears_target.value === "current" ? null : fields.arrears_target.value;
    }
    await api(active.kind, target);
    editor.close();
    month = target.month;
    if (await refresh()) showMessage($("#notice"), active.kind === "expense" ? "Spesa salvata." : "Versamento salvato.");
  } catch (error) {
    showMessage($(".form-error", entryForm), error.message);
  } finally {
    submit.disabled = false;
  }
}

async function removeEntry() {
  const control = $("#entry-delete");
  if (control.disabled || !window.confirm("Eliminare definitivamente questa registrazione?")) return;
  control.disabled = true;
  try {
    await api("remove", { kind: entry.kind, id: entry.item.id });
    editor.close();
    if (await refresh()) showMessage($("#notice"), "Registrazione eliminata.");
  } catch (error) {
    showMessage($(".form-error", entryForm), error.message);
  } finally {
    control.disabled = false;
  }
}

function editPerson(person) {
  personID = person?.id ?? null;
  $("#person-form").elements.person_name.value = person?.name || "";
  $("#person-save").textContent = person ? "Salva nome" : "Aggiungi";
  $("#person-reset").hidden = !person;
  showMessage($("#person-form .form-error"), "");
}

function drawPeople() {
  $("#people-list").replaceChildren(...data.people.map(person => {
    const item = element("li");
    item.append(element("strong", person.name), button("Rinomina", () => editPerson(person)));
    return item;
  }));
}

async function submitPerson(event) {
  event.preventDefault();
  const submit = $("#person-save");
  if (submit.disabled) return;
  submit.disabled = true;
  try {
    await api("person", { id: personID, name: event.currentTarget.elements.person_name.value });
    if (await refresh()) {
      drawPeople();
      if (bankDialog.open && bankPreview) drawBankRows();
    }
    editPerson();
  } catch (error) {
    showMessage($("#person-form .form-error"), error.message);
  } finally {
    submit.disabled = false;
  }
}

function visibleMovements() {
  const period = $("#bank-month").value;
  return bankRows.filter(item => item.day.slice(0, 7) === period);
}

function updateBankSelection() {
  const visible = visibleMovements();
  const selected = visible.filter(item => item.selected && !item.imported);
  const clean = visible.filter(item => !item.imported && !item.possible);
  const count = selected.length;
  const toggle = $("#bank-select-all");
  toggle.disabled = !clean.length;
  toggle.checked = clean.length > 0 && clean.every(item => item.selected);
  toggle.indeterminate = selected.length > 0 && !toggle.checked;
  $("#bank-import").disabled = bankSaving || !count;
  showMessage($("#bank-summary"), count ? count + " selezionate · " + money(total(selected)) : "");
}

function drawBankRows() {
  const visible = visibleMovements();
  const otherMonths = bankRows.length - visible.length;
  const details = [
    visible.length + " uscite nel mese selezionato.",
    otherMonths ? otherMonths + " in altri mesi." : "",
    bankPreview?.pending ? bankPreview.pending + " in attesa di contabilizzazione, escluse." : "",
    bankPreview?.skipped ? bankPreview.skipped + " righe non riconosciute." : "",
  ];
  showMessage($("#bank-count"), details.filter(Boolean).join(" "));
  $("#bank-list").replaceChildren(...visible.map(item => {
    const row = element("tr");
    const check = element("input");
    Object.assign(check, { type: "checkbox", checked: !!item.selected, disabled: item.imported });
    check.setAttribute("aria-label", "Seleziona " + item.description);
    check.onchange = () => { item.selected = check.checked; updateBankSelection(); };
    const selection = element("td");
    selection.append(check);
    const movement = element("td", undefined, "bank-movement");
    movement.append(element("strong", item.description), element("span", [
      dayLabel(item.day), item.category,
      item.imported ? "Già registrato" : item.possible ? "Possibile doppione" : "",
    ].filter(Boolean).join(" · "), "hint"));
    const recipient = element("td");
    const select = element("select");
    const defaultPeople = data.people.filter(person => person.id === 1 || person.id === 2);
    select.replaceChildren(option("parents", defaultPeople.map(person => person.name).join(" + ")),
      ...data.people.map(person => option(person.id, person.name)), option("custom", "Più persone…"));
    select.value = item.recipient || "parents";
    select.disabled = item.imported;
    select.title = "Addebita a";
    select.setAttribute("aria-label", "Addebita a per " + item.description);
    const group = element("fieldset", undefined, "bank-custom");
    group.append(element("legend", "Quote uguali"));
    group.hidden = select.value !== "custom";
    for (const person of data.people) {
      const choice = element("label", undefined, "choice");
      const member = element("input");
      Object.assign(member, { type: "checkbox", disabled: item.imported,
        checked: (item.recipients || [1, 2]).includes(person.id) });
      member.onchange = () => {
        item.recipients = Array.from(group.querySelectorAll("input:checked"), input => Number(input.value));
      };
      member.value = person.id;
      choice.append(member, document.createTextNode(person.name));
      group.append(choice);
    }
    select.onchange = () => {
      item.recipient = select.value;
      group.hidden = select.value !== "custom";
    };
    recipient.append(select, group);
    row.append(selection, movement, element("td", money(item.cents), "bank-amount"), recipient);
    return row;
  }));
  updateBankSelection();
}

async function previewBank(event) {
  event.preventDefault();
  const submit = $('button[type="submit"]', event.currentTarget);
  if (submit.disabled || bankSaving) return;
  submit.disabled = true;
  const error = $("#bank-form .form-error");
  const version = ++bankVersion;
  showMessage(error, "");
  showMessage($("#bank-import-error"), "");
  $("#bank-selection").hidden = true;
  bankPreview = null;
  bankRows = [];
  try {
    const file = $("#bank-file").files[0];
    let raw = $("#bank-text").value;
    let request;
    if (file) {
      if (file.size > 1_000_000) throw new Error("Il file supera 1 MB.");
      const bytes = new Uint8Array(await file.arrayBuffer());
      const excel = /\.xls$/i.test(file.name) || bytes[0] === 0xd0 && bytes[1] === 0xcf;
      if (excel) {
        const chunks = [];
        for (let index = 0; index < bytes.length; index += 16384) {
          chunks.push(String.fromCharCode(...bytes.subarray(index, index + 16384)));
        }
        request = { xls: btoa(chunks.join("")) };
      } else {
        raw = new TextDecoder().decode(bytes);
        if (raw.includes("\ufffd")) raw = new TextDecoder("windows-1252").decode(bytes);
      }
    }
    if (!request && !raw.trim()) throw new Error("Scegli un file o incolla una tabella.");
    const details = await api("bank", request || { raw });
    if (version !== bankVersion || !bankDialog.open) return;
    bankPreview = details;
    bankRows = details.movements;
    const newest = bankRows.map(item => item.day.slice(0, 7)).sort().pop();
    $("#bank-month").value = bankRows.some(item => item.day.slice(0, 7) === month) ? month : newest || month;
    $("#bank-selection").hidden = false;
    drawBankRows();
  } catch (failure) {
    if (version === bankVersion && bankDialog.open) showMessage(error, failure.message);
  } finally {
    submit.disabled = false;
  }
}

async function importSelection() {
  if (bankSaving) return;
  const period = $("#bank-month").value;
  const selected = visibleMovements().filter(item => item.selected && !item.imported);
  if (!selected.length) return;
  const error = $("#bank-import-error");
  if (selected.some(item => item.recipient === "custom" && item.recipients?.length === 0)) {
    showMessage(error, "Seleziona almeno una persona per ogni spesa da ripartire.");
    return;
  }
  bankSaving = true;
  bankDialog.querySelector(".close").disabled = true;
  $("#bank-form").inert = true;
  $("#bank-selection").inert = true;
  showMessage(error, "");
  updateBankSelection();
  try {
    const result = await api("bank/import", { month: period, movements: selected.map(item => ({
      key: item.key, day: item.day, description: item.description, cents: item.cents,
      people: item.recipient === "custom" ? item.recipients || [1, 2]
        : item.recipient && item.recipient !== "parents" ? [Number(item.recipient)] : [1, 2],
    })) });
    selected.forEach(item => { item.imported = true; item.selected = false; });
    month = period;
    if (await refresh()) {
      showMessage($("#notice"), result.count === 1 ? "1 spesa importata." : result.count + " spese importate.");
    }
    drawBankRows();
    showMessage(error, "");
    $("#bank-count").textContent += result.count === 1 ? " 1 spesa salvata." : " " + result.count + " spese salvate.";
  } catch (failure) {
    showMessage(error, failure.message);
  } finally {
    bankSaving = false;
    bankDialog.querySelector(".close").disabled = false;
    $("#bank-form").inert = false;
    $("#bank-selection").inert = false;
    updateBankSelection();
  }
}

function saveDownload(content, name) {
  const blob = new Blob([content], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = element("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function clearBank() {
  ++bankVersion;
  bankRows = [];
  bankPreview = null;
  $("#bank-form").reset();
  $("#bank-selection").hidden = true;
  $("#bank-list").replaceChildren();
  showMessage($("#bank-form .form-error"), "");
  showMessage($("#bank-import-error"), "");
}

function receiptLines(title, entries) {
  const group = element("section");
  group.append(element("h3", title));
  const list = element("dl");
  entries.forEach(item => field(list, item.label, money(item.cents)));
  group.append(entries.length ? list : element("p", "Nessuna registrazione."));
  return group;
}

function receiptData() {
  const form = $("#print-form").elements;
  const person = Number(form.receipt_person.value);
  const people = person ? data.people.filter(item => item.id === person) : data.people;
  return {
    version: 1, month, period: monthLabel(month), paper: Number(form.paper.value),
    people: people.map(item => {
      const { owed, received, balance } = summarize(item.id);
      const expenses = data.expenses.flatMap(expense => expense.shares.filter(share => share.person_id === item.id)
        .map(share => ({ label: dayLabel(expense.day) + " · " + expense.description, cents: share.cents })));
      const payments = data.credits.filter(payment => payment.person_id === item.id)
        .map(payment => ({ label: [
          dayLabel(payment.day), payment.note,
          payment.recorded_month !== month ? "Saldo ricevuto in " + monthLabel(payment.recorded_month) : "",
        ].filter(Boolean).join(" · "), cents: payment.cents }));
      const arrears = data.arrears.filter(row => row.person_id === item.id)
        .map(row => ({ label: monthLabel(row.month), cents: row.cents }));
      return { name: item.name, owed, received, balance, expenses, payments, arrears };
    }),
  };
}

function printReceipt(event) {
  event.preventDefault();
  const documentData = receiptData();
  const receipt = $("#receipt");
  receipt.className = documentData.paper === 80 ? "paper-80" : "paper-58";
  receipt.replaceChildren(element("h1", "Rendiconto familiare"),
    element("p", documentData.period, "receipt-period"));
  for (const item of documentData.people) {
    const personReceipt = element("article");
    const amounts = element("dl");
    field(amounts, "Dovuto", money(item.owed));
    field(amounts, "Ricevuto", money(item.received));
    field(amounts, balanceLabel(item.balance), money(Math.abs(item.balance)));
    personReceipt.append(element("h2", item.name), receiptLines("Spese (quote)", item.expenses),
      receiptLines("Versamenti", item.payments), amounts);
    if (item.arrears.length) {
      personReceipt.append(receiptLines("Arretrati per mese", item.arrears));
      const all = element("dl");
      field(all, "Totale da ricevere", money(Math.max(item.balance, 0) + total(item.arrears)));
      personReceipt.append(all);
    }
    receipt.append(personReceipt);
  }
  printDialog.close();
  window.print();
}

function downloadReceipt() {
  const documentData = receiptData();
  saveDownload(JSON.stringify(documentData), "Rendiconto-" + documentData.month + ".rendiconto");
  printDialog.close();
  showMessage($("#notice"), "Apri il file .rendiconto scaricato in ScontrinoStudio sul Mac.");
}

$("#previous").onclick = () => moveMonth(-1);
$("#next").onclick = () => moveMonth(1);
monthInput.onchange = () => setMonth(monthInput.value);
$("#history").onchange = event => setMonth(event.currentTarget.value);
$("#new-expense").onclick = () => openEntry("expense");
$("#new-payment").onclick = () => openEntry("payment");
$("#entry-delete").onclick = removeEntry;
entryForm.onsubmit = submitEntry;
$("#people-open").onclick = () => { drawPeople(); editPerson(); peopleDialog.showModal(); };
$("#person-reset").onclick = () => editPerson();
$("#person-form").onsubmit = submitPerson;
$("#bank-open").onclick = () => bankDialog.showModal();
bankDialog.onclose = clearBank;
bankDialog.oncancel = event => { if (bankSaving) event.preventDefault(); };
$("#bank-form").onsubmit = previewBank;
$("#bank-month").onchange = () => {
  showMessage($("#bank-import-error"), "");
  drawBankRows();
};
$("#bank-people").onclick = $("#people-open").onclick;
$("#bank-select-all").onchange = event => {
  const checked = event.currentTarget.checked;
  visibleMovements().filter(item => !item.imported && !item.possible)
    .forEach(item => { item.selected = checked; });
  drawBankRows();
  $("#bank-select-all").focus();
};
$("#bank-import").onclick = importSelection;
const entryFields = entryForm.elements;
entryFields.person.onchange = () => loadAllocationChoices("");
entryFields.month.onchange = () => { if (entry.kind === "payment") loadAllocationChoices(); };
entryFields.arrears_target.onchange = drawAllocationNote;
entryFields.amount.oninput = drawAllocationNote;
editor.onclose = () => {
  ++allocationVersion;
  $('button[type="submit"]', entryForm).disabled = false;
};
$("#print-open").onclick = () => {
  $("#print-form").elements.receipt_person.replaceChildren(option(0, "Tutte le persone"),
    ...data.people.map(person => option(person.id, person.name)));
  printDialog.showModal();
};
$("#print-form").onsubmit = printReceipt;
$("#scontrinostudio").onclick = downloadReceipt;
document.querySelectorAll("dialog .close").forEach(control => {
  control.onclick = () => control.closest("dialog").close();
});
monthInput.value = month;
$("#period").textContent = monthLabel(month);
createActions.forEach(selector => { $(selector).disabled = true; });
refresh();
