import { createContext, useContext, useEffect, useState } from "react";
import { bootstrapMerchant, getStoredMerchant, setStoredMerchant } from "../lib/api.js";

const MerchantCtx = createContext(null);

export function MerchantProvider({ children }) {
  const [merchantId, setMerchantId] = useState(getStoredMerchant());
  const [ready, setReady] = useState(!!getStoredMerchant());

  useEffect(() => {
    if (merchantId) return;
    let cancelled = false;
    bootstrapMerchant().then(({ merchantId: id }) => {
      if (!cancelled) {
        setMerchantId(id);
        setReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setMerchant = (id) => {
    const trimmed = id.trim();
    setStoredMerchant(trimmed);
    setMerchantId(trimmed);
  };

  return (
    <MerchantCtx.Provider value={{ merchantId, setMerchant, ready }}>
      {children}
    </MerchantCtx.Provider>
  );
}

export function useMerchant() {
  const ctx = useContext(MerchantCtx);
  if (!ctx) throw new Error("useMerchant must be used within MerchantProvider");
  return ctx;
}
