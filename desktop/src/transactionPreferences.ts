import type {RuntimeTransport} from "./runtime";
import type {Preferences} from "./preferences";

export interface TransactionSettings {automatic_transactions: boolean}

function settings(value: unknown): TransactionSettings {
  if (!value || typeof value !== "object" || typeof (value as TransactionSettings).automatic_transactions !== "boolean") {
    throw new Error("Configuração de transações inválida.");
  }
  return {automatic_transactions: (value as TransactionSettings).automatic_transactions};
}

export async function readTransactionSettings(transport: RuntimeTransport) {
  return settings(await transport.request("transactions.settings.get"));
}

export async function saveTransactionSettings(transport: RuntimeTransport, automaticTransactions: boolean) {
  return settings(await transport.request("transactions.settings.set", {automatic_transactions: automaticTransactions}));
}

/** An unrelated settings edit must not replace a policy whose initial read is still pending. */
export async function applyTransactionPreferences(transport: RuntimeTransport, preferences: Preferences, edited: boolean) {
  const value=edited ? await saveTransactionSettings(transport,preferences.automaticTransactions) : await readTransactionSettings(transport);
  return {...preferences,automaticTransactions:value.automatic_transactions};
}
