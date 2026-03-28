import React, { useState, useRef, useEffect, useCallback } from "react";

const PASSCODE = "1980";

export default function PasscodeGate({ onUnlock }) {
  const [digits, setDigits] = useState(["", "", "", ""]);
  const [error, setError] = useState(false);
  const [success, setSuccess] = useState(false);
  const [pressed, setPressed] = useState(null);
  const hiddenRef = useRef(null);
  const timersRef = useRef([]);

  useEffect(() => {
    hiddenRef.current?.focus();
    return () => timersRef.current.forEach(clearTimeout);
  }, []);

  const checkCode = useCallback((next) => {
    const code = next.join("");
    if (code === PASSCODE) {
      setSuccess(true);
      timersRef.current.push(setTimeout(() => onUnlock(), 800));
    } else {
      setError(true);
      timersRef.current.push(
        setTimeout(() => {
          setDigits(["", "", "", ""]);
          setError(false);
          hiddenRef.current?.focus();
        }, 600)
      );
    }
  }, [onUnlock]);

  const addDigit = useCallback((char) => {
    setDigits((prev) => {
      const idx = prev.findIndex((d) => d === "");
      if (idx === -1) return prev;
      const next = [...prev];
      next[idx] = String(char);
      setError(false);
      if (idx === 3) {
        // defer check to next tick so state updates first
        setTimeout(() => checkCode(next), 0);
      }
      return next;
    });
  }, [checkCode]);

  const removeDigit = useCallback(() => {
    setDigits((prev) => {
      const lastFilled = prev.reduce((acc, d, i) => (d !== "" ? i : acc), -1);
      if (lastFilled < 0) return prev;
      const next = [...prev];
      next[lastFilled] = "";
      setError(false);
      return next;
    });
  }, []);

  const handleInput = (e) => {
    const val = e.target.value.replace(/\D/g, "");
    if (val) addDigit(val[val.length - 1]);
    e.target.value = "";
  };

  const handleKeyDown = (e) => {
    if (e.key === "Backspace") {
      e.preventDefault();
      removeDigit();
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 4);
    if (pasted.length === 4) {
      const next = pasted.split("");
      setDigits(next);
      checkCode(next);
    }
  };

  const tapKey = (key) => {
    setPressed(key);
    setTimeout(() => setPressed(null), 120);
    if (key === "del") {
      removeDigit();
    } else {
      addDigit(key);
    }
  };

  const filledCount = digits.filter((d) => d !== "").length;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        background: "#f5f5f7",
        fontFamily: "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif",
        userSelect: "none",
        WebkitUserSelect: "none",
        overflow: "hidden",
      }}
      onClick={() => hiddenRef.current?.focus()}
    >
      {/* Soft ambient light */}
      <div
        style={{
          position: "absolute",
          top: "20%",
          left: "50%",
          transform: "translateX(-50%)",
          width: "min(600px, 100vw)",
          height: "min(600px, 100vw)",
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(255,255,255,0.8) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          position: "relative",
          zIndex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          animation: "fadeUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) both",
        }}
      >
        {/* Lock / Check icon */}
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: 24,
            transition: "all 0.5s cubic-bezier(0.16, 1, 0.3, 1)",
            background: success
              ? "rgba(52, 199, 89, 0.1)"
              : error
              ? "rgba(255, 59, 48, 0.08)"
              : "rgba(0, 0, 0, 0.04)",
            animation: error ? "shake 0.5s cubic-bezier(0.36, 0.07, 0.19, 0.97) both" : undefined,
          }}
        >
          {success ? (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#34c759" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          ) : (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={error ? "rgba(255,59,48,0.6)" : "rgba(0,0,0,0.25)"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ transition: "stroke 0.3s ease" }}>
              <rect x="3" y="11" width="18" height="11" rx="2.5" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          )}
        </div>

        {/* Title */}
        <p
          style={{
            fontSize: 14,
            fontWeight: 500,
            letterSpacing: "-0.01em",
            marginBottom: 32,
            transition: "all 0.4s ease",
            color: success
              ? "#34c759"
              : error
              ? "rgba(255, 59, 48, 0.7)"
              : "rgba(0, 0, 0, 0.35)",
          }}
        >
          {success ? "Welcome" : error ? "Incorrect passcode" : "Enter passcode"}
        </p>

        {/* Dots */}
        <div style={{ display: "flex", gap: 16, marginBottom: 48 }}>
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              style={{
                width: 14,
                height: 14,
                borderRadius: "50%",
                transition: "all 0.25s cubic-bezier(0.16, 1, 0.3, 1)",
                transform: digits[i] ? "scale(1)" : "scale(1)",
                background: success
                  ? "#34c759"
                  : error
                  ? "#ff3b30"
                  : digits[i]
                  ? "#1d1d1f"
                  : "transparent",
                border: success
                  ? "2px solid #34c759"
                  : error
                  ? "2px solid #ff3b30"
                  : digits[i]
                  ? "2px solid #1d1d1f"
                  : "2px solid rgba(0, 0, 0, 0.15)",
                boxShadow: success
                  ? "0 0 12px rgba(52, 199, 89, 0.3)"
                  : digits[i] && !error
                  ? "0 1px 3px rgba(0, 0, 0, 0.1)"
                  : "none",
              }}
            />
          ))}
        </div>

        {/* Hidden input */}
        <input
          ref={hiddenRef}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            opacity: 0,
            pointerEvents: "none",
          }}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onBlur={() => {
            timersRef.current.push(setTimeout(() => hiddenRef.current?.focus(), 100));
          }}
        />

        {/* Number pad */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "clamp(8px, 2vw, 12px)",
            width: "clamp(220px, 72vw, 270px)",
          }}
        >
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, null, 0, "del"].map((key, i) => {
            if (key === null) return <div key={i} />;
            const isDel = key === "del";
            const isPressed = pressed === key;

            return (
              <button
                key={i}
                type="button"
                onClick={() => tapKey(key)}
                style={{
                  width: "clamp(60px, 20vw, 78px)",
                  height: "clamp(60px, 20vw, 78px)",
                  borderRadius: "50%",
                  border: "none",
                  outline: "none",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexDirection: "column",
                  transition: "all 0.15s ease",
                  WebkitTapHighlightColor: "transparent",
                  background: isDel
                    ? "transparent"
                    : isPressed
                    ? "rgba(0, 0, 0, 0.08)"
                    : "rgba(0, 0, 0, 0.03)",
                  transform: isPressed && !isDel ? "scale(0.95)" : "scale(1)",
                }}
              >
                {isDel ? (
                  <svg
                    width="22"
                    height="22"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="rgba(0,0,0,0.35)"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M9.37 5.51A1.5 1.5 0 0 1 10.43 5H18a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-7.57a1.5 1.5 0 0 1-1.06-.44L3 12l6.37-6.49z" />
                    <line x1="14" y1="9" x2="14" y2="9.01" />
                    <path d="M13 10l2 2m0-2l-2 2" />
                  </svg>
                ) : (
                  <>
                    <span
                      style={{
                        fontSize: 28,
                        fontWeight: 300,
                        color: "#1d1d1f",
                        lineHeight: 1,
                        letterSpacing: "-0.02em",
                      }}
                    >
                      {key}
                    </span>
                    {key !== 0 && (
                      <span
                        style={{
                          fontSize: 9,
                          fontWeight: 500,
                          color: "rgba(0,0,0,0.2)",
                          letterSpacing: "0.12em",
                          marginTop: 2,
                        }}
                      >
                        {["", "ABC", "DEF", "GHI", "JKL", "MNO", "PQRS", "TUV", "WXYZ"][key] || ""}
                      </span>
                    )}
                  </>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <style>{`
        @keyframes shake {
          10%, 90% { transform: translateX(-1.5px); }
          20%, 80% { transform: translateX(3px); }
          30%, 50%, 70% { transform: translateX(-5px); }
          40%, 60% { transform: translateX(5px); }
        }
        @keyframes fadeUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>
    </div>
  );
}
