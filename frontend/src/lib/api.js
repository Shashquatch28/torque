// Thin fetch wrapper — same origin, same tenant-scoped paths the vanilla-JS
// frontend used. This module never computes a metric; it only moves JSON.

export async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail || detail;
    } catch (e) {
      /* not JSON */
    }
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.status === 204 ? null : r.json();
}

const MERCHANT_KEY = "torque.merchant";

export function getStoredMerchant() {
  return localStorage.getItem(MERCHANT_KEY) || "";
}

export function setStoredMerchant(id) {
  localStorage.setItem(MERCHANT_KEY, id);
}

export async function bootstrapMerchant() {
  try {
    const d = await api("/demo/merchant");
    setStoredMerchant(d.merchant_id);
    return { merchantId: d.merchant_id, seeded: d.seeded };
  } catch (e) {
    setStoredMerchant("acc_demo");
    return { merchantId: "acc_demo", seeded: false, error: true };
  }
}
