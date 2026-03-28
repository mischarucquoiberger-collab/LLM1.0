import React, { useState, useRef, useEffect } from "react";
import { Search, Building2, Loader2, ArrowRight } from "lucide-react";
import { useCircleTransition } from "@/components/CircleTransition";
import { startReport } from "@/api/backend";
import companies from "@/data/companies.json";

const MAX_RESULTS = 20;

const COMPANY_INDEX = companies
  .map((c) => ({
    ...c,
    tickerLower: String(c.ticker || "").toLowerCase(),
    nameLower: String(c.name || "").toLowerCase(),
  }))
  .sort((a, b) => a.tickerLower.localeCompare(b.tickerLower));

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [filteredCompanies, setFilteredCompanies] = useState(COMPANY_INDEX.slice(0, MAX_RESULTS));
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const inputRef = useRef(null);
  const containerRef = useRef(null);
  const dropdownRef = useRef(null);
  const isKeyNav = useRef(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const { navigateWithReveal } = useCircleTransition();

  useEffect(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      setFilteredCompanies(COMPANY_INDEX.slice(0, MAX_RESULTS));
      setHighlightIdx(-1);
      return;
    }
    const isTickerQuery = /^\d/.test(q);
    const results = COMPANY_INDEX.filter((c) => {
      if (isTickerQuery) return c.tickerLower.startsWith(q);
      return c.nameLower.includes(q) || c.tickerLower.includes(q);
    }).slice(0, MAX_RESULTS);
    setFilteredCompanies(results);
    setHighlightIdx(results.length > 0 ? 0 : -1);
  }, [query]);

  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsFocused(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        setIsFocused(true);
      }
      if (e.key === "Escape") {
        inputRef.current?.blur();
        setIsFocused(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const launchReport = (ticker, name = "", mode = "full", event) => {
    const code = (ticker || "").trim();
    if (!code) return;
    setIsSubmitting(true);
    setError(null);

    const promise = startReport({ stock_code: code, company_name: name, mode })
      .then((response) => {
        const jobId = response?.job_id;
        if (!jobId) throw new Error("Job ID missing");
        return `/GenerateReport?jobId=${jobId}&ticker=${encodeURIComponent(code)}&name=${encodeURIComponent(name || "")}&mode=${mode}`;
      })
      .catch((err) => {
        setError(err.message || "Failed to start report");
        return null;
      })
      .finally(() => setIsSubmitting(false));

    navigateWithReveal(promise, event);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (highlightIdx >= 0 && filteredCompanies[highlightIdx]) {
      const c = filteredCompanies[highlightIdx];
      launchReport(c.ticker, c.name, "full", e);
    } else {
      launchReport(query, "", "full", e);
    }
  };

  const handleSelectCompany = (company, event) => {
    launchReport(company.ticker, company.name, "full", event);
  };

  const handleKeyDown = (e) => {
    if (!isFocused || filteredCompanies.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      isKeyNav.current = true;
      setHighlightIdx((p) => (p + 1) % filteredCompanies.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      isKeyNav.current = true;
      setHighlightIdx((p) => (p - 1 + filteredCompanies.length) % filteredCompanies.length);
    }
  };

  const showDropdown = isFocused && !isSubmitting;

  return (
    <div ref={containerRef} className="relative w-full">
      <form onSubmit={handleSubmit}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.85rem",
            padding: "0.95rem 1.25rem",
            background: isFocused ? "#fff" : "rgba(0,0,0,0.025)",
            border: `1px solid ${isFocused ? "rgba(0,0,0,0.12)" : "transparent"}`,
            borderRadius: 12,
            transition: "all 0.4s cubic-bezier(0.16,1,0.3,1)",
            boxShadow: isFocused ? "0 8px 32px rgba(0,0,0,0.06)" : "none",
          }}
        >
          {isSubmitting ? (
            <Loader2 size={18} style={{ color: "rgba(0,0,0,0.4)", flexShrink: 0, animation: "spin 1s linear infinite" }} />
          ) : (
            <Search size={18} style={{ color: isFocused ? "#0a0a0a" : "rgba(0,0,0,0.4)", flexShrink: 0, transition: "color 0.3s ease" }} />
          )}
          <input
            ref={inputRef}
            className="search-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onKeyDown={handleKeyDown}
            placeholder="Search by company name or stock code..."
            disabled={isSubmitting}
            style={{
              width: "100%",
              border: "none",
              outline: "none",
              background: "none",
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "0.9rem",
              fontWeight: 400,
              color: "#0a0a0a",
            }}
          />
          {query && !isSubmitting && (
            <button
              type="button"
              onClick={() => { setQuery(""); inputRef.current?.focus(); }}
              style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.65rem",
                fontWeight: 500,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "rgba(0,0,0,0.25)",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 8px",
                borderRadius: 4,
                flexShrink: 0,
                transition: "color 0.15s ease",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.6)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(0,0,0,0.25)"; }}
            >
              Clear
            </button>
          )}
          {(isFocused || query) && (
            <button
              type="submit"
              disabled={isSubmitting}
              style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.65rem",
                fontWeight: 500,
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                background: "#0a0a0a",
                color: "#fff",
                border: "none",
                padding: "8px 20px",
                borderRadius: 100,
                cursor: "pointer",
                flexShrink: 0,
                transition: "background 0.2s ease",
                opacity: isSubmitting ? 0.4 : 1,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "#333"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "#0a0a0a"; }}
            >
              Generate
            </button>
          )}
        </div>
      </form>

      {/* Error */}
      {error && (
        <p style={{
          marginTop: 8,
          fontFamily: "'Space Grotesk', sans-serif",
          fontSize: "0.75rem",
          color: "#cc3333",
        }}>
          {error}
        </p>
      )}

      {/* Dropdown */}
      {showDropdown && (
        <div
          ref={dropdownRef}
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            marginTop: 8,
            zIndex: 50,
            background: "#fff",
            border: "1px solid rgba(0,0,0,0.08)",
            borderRadius: 12,
            boxShadow: "0 12px 40px rgba(0,0,0,0.08)",
            maxHeight: "min(420px, 50vh)",
            overflowY: "auto",
            overflowX: "hidden",
            overscrollBehavior: "contain",
          }}
        >
          {!query && (
            <div style={{ padding: "12px 16px 6px" }}>
              <span style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.6rem",
                textTransform: "uppercase",
                letterSpacing: "0.25em",
                color: "rgba(0,0,0,0.3)",
                fontWeight: 500,
              }}>
                Popular
              </span>
            </div>
          )}

          <div style={{ padding: "4px 0" }}>
            {filteredCompanies.map((company, idx) => (
              <button
                type="button"
                key={company.ticker}
                ref={(el) => {
                  if (highlightIdx === idx && el && isKeyNav.current) {
                    isKeyNav.current = false;
                    const dd = dropdownRef.current;
                    if (dd) {
                      const et = el.offsetTop;
                      const eb = et + el.offsetHeight;
                      if (et < dd.scrollTop) dd.scrollTo({ top: et, behavior: "smooth" });
                      else if (eb > dd.scrollTop + dd.clientHeight) dd.scrollTo({ top: eb - dd.clientHeight, behavior: "smooth" });
                    }
                  }
                }}
                onClick={(e) => handleSelectCompany(company, e)}
                onMouseEnter={() => { isKeyNav.current = false; setHighlightIdx(idx); }}
                style={{
                  width: "100%",
                  textAlign: "left",
                  border: "none",
                  background: highlightIdx === idx ? "rgba(0,0,0,0.03)" : "none",
                  cursor: "pointer",
                  padding: "10px 16px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  transition: "background 0.1s ease",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 7,
                      background: highlightIdx === idx ? "rgba(0,0,0,0.06)" : "rgba(0,0,0,0.03)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      transition: "background 0.1s ease",
                    }}
                  >
                    <Building2 size={14} style={{ color: "rgba(0,0,0,0.3)" }} />
                  </div>
                  <div>
                    <span style={{
                      fontFamily: "'Space Grotesk', sans-serif",
                      fontWeight: 500,
                      color: "#0a0a0a",
                      fontSize: "0.85rem",
                      display: "block",
                    }}>
                      {company.name}
                    </span>
                    <span style={{
                      fontFamily: "'Space Grotesk', sans-serif",
                      fontSize: "0.7rem",
                      color: "var(--color-accent, #de5f40)",
                      fontWeight: 500,
                      letterSpacing: "0.05em",
                    }}>
                      {company.ticker}
                    </span>
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  style={{
                    color: "#0a0a0a",
                    opacity: highlightIdx === idx ? 0.25 : 0,
                    transform: highlightIdx === idx ? "translateX(0)" : "translateX(-3px)",
                    transition: "all 0.12s ease",
                  }}
                />
              </button>
            ))}
          </div>

          {query && filteredCompanies.length === 0 && (
            <div style={{ padding: "2.5rem", textAlign: "center" }}>
              <Search size={20} style={{ color: "rgba(0,0,0,0.1)", margin: "0 auto 12px", display: "block" }} />
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", color: "rgba(0,0,0,0.35)", fontSize: "0.85rem" }}>
                No results for "{query}"
              </p>
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", color: "rgba(0,0,0,0.18)", fontSize: "0.75rem", marginTop: 4 }}>
                Try a ticker code or company name
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
