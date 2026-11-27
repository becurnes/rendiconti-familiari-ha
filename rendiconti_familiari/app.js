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
let data = { people: [], expenses: [], payments: [], months: [], arrears: [] };
let loadVersion = 0;
let entry = null;
let personID = null;
let bankRows = [];
let openBankVersion = 0;

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
    const error = new Error(body.error || "Operazione non riuscita.");
    error.status = response.status;
    throw error;
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
  const payments = data.payments.filter(payment => payment.person_id === personID);
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
  const received = total(data.payments);
  const summaries = data.people.map(person => ({ ...person, ...summarize(person.id) }));
  const remaining = summaries.reduce((sum, person) => sum + Math.max(person.balance, 0), 0);
  const arrears = total(data.arrears);
  const totals = element("dl");
  field(totals, "Spese anticipate", money(owed));
  field(totals, "Versamenti ricevuti", money(received));
  field(totals, "Residuo del mese", money(remaining));
  field(totals, "Arretrati", money(arrears));
  field(totals, "Totale da ricevere", money(remaining + arrears), "highlight");
  $("#totals").replaceChildren(totals);

  const cards = summaries.map(person => {
    const card = element("article", undefined, "person-card");
    const head = element("div", undefined, "section-head");
    const status = person.balance < 0 ? "In eccedenza" : person.balance > 0 ? "Da saldare"
      : person.owed ? "Saldato" : "";
    head.append(element("h3", person.name));
    if (status) head.append(element("span", status, person.balance > 0 ? "status due" : "status"));
    const amounts = element("dl");
    field(amounts, "Dovuto", money(person.owed));
    field(amounts, "Ricevuto", money(person.received));
    field(amounts, balanceLabel(person.balance), money(Math.abs(person.balance)));
    const past = data.arrears.filter(item => item.person_id === person.id);
    if (past.length) {
      field(amounts, "Arretrati", money(total(past)));
      field(amounts, "Totale da ricevere", money(Math.max(person.balance, 0) + total(past)));
    }
    card.append(head, amounts, button("Registra versamento", () => openEntry("payment", { person_id: person.id })));
    return card;
  });
  $("#cards").replaceChildren(...cards);
  $("#arrears").hidden = !data.arrears.length;
  $("#arrears-list").replaceChildren(...data.arrears.map(item => {
    const row = record(personName(item.person_id), monthLabel(item.month), money(item.cents),
      () => openEntry("payment", item), "Registra acconto");
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
    record(personName(payment.person_id), [dayLabel(payment.day), payment.note].filter(Boolean).join(" · "),
      money(payment.cents), () => openEntry("payment", payment)))
    : [element("li", "Nessun versamento in questo mese.", "empty")]));
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
      if (error.status === 401) showAccess();
      else showMessage($("#notice"), error.message);
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

function openEntry(kind, item = {}, fromBank = false) {
  entry = { kind, item, fromBank };
  const form = entryForm.elements;
  const expense = kind === "expense";
  const target = item.month || (fromBank ? item.day.slice(0, 7) : month);
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
  editor.showModal();
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
    }
    await api(active.kind, target);
    if (active.fromBank) {
      active.item.imported = true;
      drawBankRows();
    }
    editor.close();
    if (!active.item.month) month = target.month;
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
    if (await refresh()) drawPeople();
    editPerson();
  } catch (error) {
    showMessage($("#person-form .form-error"), error.message);
  } finally {
    submit.disabled = false;
  }
}

function drawBankRows() {
  $("#bank-list").replaceChildren(...bankRows.map(item => {
    const row = record(item.description,
      [dayLabel(item.day), item.imported ? "Già registrato" : item.possible ? "Possibile doppione" : ""].filter(Boolean).join(" · "),
      money(item.cents), () => openEntry("expense", item, true), "Usa");
    if (item.imported) $("button", row).disabled = true;
    return row;
  }));
}

async function previewBank(event) {
  event.preventDefault();
  const submit = $('button[type="submit"]', event.currentTarget);
  if (submit.disabled) return;
  submit.disabled = true;
  const error = $("#bank-form .form-error");
  const version = openBankVersion;
  showMessage(error, "");
  try {
    const file = $("#bank-file").files[0];
    let raw = $("#bank-text").value;
    if (file && !raw.trim()) {
      if (file.size > 1_000_000) throw new Error("Seleziona un file inferiore a 1 MB.");
      const bytes = await file.arrayBuffer();
      raw = new TextDecoder().decode(bytes);
      if (raw.includes("\ufffd")) raw = new TextDecoder("windows-1252").decode(bytes);
    }
    const details = await api("bank", { raw });
    if (version !== openBankVersion || !bankDialog.open) return;
    bankRows = details.movements;
    showMessage($("#bank-count"), details.movements.length + " uscite trovate." +
      (details.skipped ? " Righe non lette: " + details.skipped + "." : ""));
    drawBankRows();
  } catch (failure) {
    if (version !== openBankVersion || !bankDialog.open) return;
    bankRows = [];
    showMessage($("#bank-count"), "");
    drawBankRows();
    showMessage(error, failure.message);
  } finally {
    submit.disabled = false;
  }
}

function openBankRequest(action, values = {}) {
  return api("open-banking", { action, ...values });
}

function updateOpenBank(state) {
  $("#ob-setup").hidden = Boolean(state.application);
  $("#ob-app-id").value = state.application;
  $("#ob-redirect").value = state.redirect;
  $("#ob-session-actions").hidden = !state.application;
  $("#ob-start").hidden = !state.application || state.hasSession;
  $("#ob-end").hidden = !state.hasSession;
  $("#ob-edit").hidden = state.hasSession;
  $("#ob-refresh").hidden = !state.connected;
  $("#ob-finish").hidden = !state.pending;
  $("#ob-bank-link").hidden = true;
  $("#ob-return").value = "";
  $("#ob-select").hidden = !state.choices.length;
  $("#ob-accounts").replaceChildren(...state.choices.map(item => option(item.index, item.label)));
  $("#ob-certificate").textContent = state.certificate ? "Scarica certificato pubblico" : "Genera e scarica certificato pubblico";
  const expiry = new Date(state.expires);
  const expires = Number.isNaN(expiry.getTime()) ? "" : " · Consenso fino al " + dateFormat.format(expiry);
  const message = state.connected ? state.account + expires
    : state.choices.length ? "Scegli il conto da consultare."
      : state.hasSession ? "Nessun conto disponibile. Scollega la sessione e verifica il conto abilitato in Enable Banking."
        : "Conto non collegato.";
  showMessage($("#ob-status"), message);
}

async function runOpenBank(action, values, complete = updateOpenBank) {
  const version = ++openBankVersion;
  const section = $("#open-banking");
  section.inert = true;
  section.setAttribute("aria-busy", "true");
  showMessage($("#ob-error"), "");
  try {
    const payload = await openBankRequest(action, values);
    if (version === openBankVersion && bankDialog.open) complete(payload);
  } catch (error) {
    if (version === openBankVersion && bankDialog.open) {
      showMessage($("#ob-error"), error.message);
      if (action === "status") {
        ["#ob-setup", "#ob-session-actions", "#ob-finish", "#ob-select", "#ob-refresh"]
          .forEach(selector => { $(selector).hidden = true; });
        showMessage($("#ob-status"), "");
      }
    }
  } finally {
    if (version === openBankVersion) {
      section.inert = false;
      section.removeAttribute("aria-busy");
    }
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
  ++openBankVersion;
  bankRows = [];
  drawBankRows();
  $("#bank-form").reset();
  $("#ob-return").value = "";
  $("#ob-bank-link").removeAttribute("href");
  $("#ob-bank-link").hidden = true;
  showMessage($("#bank-count"), "");
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
      const payments = data.payments.filter(payment => payment.person_id === item.id)
        .map(payment => ({ label: [dayLabel(payment.day), payment.note].filter(Boolean).join(" · "), cents: payment.cents }));
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

function showAccess() {
  data = { people: [], expenses: [], payments: [], months: [], arrears: [] };
  clearBank();
  document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close());
  $("#receipt").replaceChildren();
  draw();
  showMessage($("#notice"), "");
  $("#app").hidden = true;
  $("#access").hidden = false;
  $("#access-form").elements.password.focus();
}

async function signIn(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = $('button[type="submit"]', form);
  if (submit.disabled) return;
  submit.disabled = true;
  showMessage($(".form-error", form), "");
  try {
    await api("login", { password: form.elements.password.value });
    form.reset();
    $("#access").hidden = true;
    $("#app").hidden = false;
    $("#logout").hidden = false;
    await refresh();
  } catch (error) {
    showMessage($(".form-error", form), error.message);
  } finally {
    submit.disabled = false;
  }
}

async function signOut() {
  try {
    await api("logout", {});
    ++loadVersion;
    showAccess();
  } catch (error) {
    showMessage($("#notice"), error.message);
  }
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
$("#bank-open").onclick = () => {
  bankDialog.showModal();
  runOpenBank("status", {});
};
bankDialog.onclose = clearBank;
$("#ob-edit").onclick = () => { $("#ob-setup").hidden = false; };
$("#ob-certificate").onclick = () => runOpenBank("certificate", {}, payload => {
  saveDownload(payload.pem, "rendiconti-enablebanking.crt");
  $("#ob-certificate").textContent = "Scarica certificato pubblico";
});
$("#ob-setup").onsubmit = event => {
  event.preventDefault();
  runOpenBank("configure", { application: $("#ob-app-id").value.trim(), redirect: $("#ob-redirect").value });
};
$("#ob-start").onclick = () => runOpenBank("start", {}, payload => {
  $("#ob-finish").hidden = false;
  const link = $("#ob-bank-link");
  link.href = payload.url;
  link.hidden = false;
  $("#ob-return").value = "";
});
$("#ob-finish").onsubmit = event => {
  event.preventDefault();
  const callback = $("#ob-return").value;
  $("#ob-return").value = "";
  runOpenBank("finish", { callback });
};
$("#ob-select").onsubmit = event => {
  event.preventDefault();
  runOpenBank("select", { index: Number($("#ob-accounts").value) });
};
$("#ob-end").onclick = () => {
  if (!window.confirm("Scollegare il conto BPER?")) return;
  runOpenBank("disconnect", {}, state => {
    bankRows = [];
    drawBankRows();
    showMessage($("#bank-count"), "");
    updateOpenBank(state);
  });
};
$("#ob-refresh").onclick = () => runOpenBank("movements", { month }, payload => {
  bankRows = payload.movements;
  showMessage($("#bank-count"), monthLabel(month) + " · " + bankRows.length + " uscite contabilizzate.");
  drawBankRows();
});
$("#bank-form").onsubmit = previewBank;
$("#print-open").onclick = () => {
  $("#print-form").elements.receipt_person.replaceChildren(option(0, "Tutte le persone"),
    ...data.people.map(person => option(person.id, person.name)));
  printDialog.showModal();
};
$("#print-form").onsubmit = printReceipt;
$("#scontrinostudio").onclick = downloadReceipt;
$("#logout").onclick = signOut;
$("#access-form").onsubmit = signIn;
document.querySelectorAll("dialog .close").forEach(control => {
  control.onclick = () => control.closest("dialog").close();
});
monthInput.value = month;
$("#period").textContent = monthLabel(month);
api("session").then(session => {
  $("#logout").hidden = !session.direct;
  return refresh();
}).catch(error => {
  if (error.status === 401) showAccess();
  else showMessage($("#notice"), error.message);
});
createActions.forEach(selector => { $(selector).disabled = true; });
