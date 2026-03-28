import React from "react";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { useCircleTransition } from "@/components/CircleTransition";
import SearchBar from "@/components/home/SearchBar";

const ease = [0.16, 1, 0.3, 1];

export default function SearchModeToggle() {
  const { navigateWithReveal } = useCircleTransition();

  return (
    <div className="w-full">
      <SearchBar />

      <motion.div
        className="flex items-center justify-center gap-4 mt-5"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4, duration: 0.5, ease }}
      >
        <motion.button
          type="button"
          onClick={(e) => navigateWithReveal("/Query", e, { animate: true })}
          className="inline-flex items-center gap-1.5"
          style={{
            fontSize: 12,
            color: "rgba(0, 51, 204, 0.28)",
            fontFamily: "'Inter', system-ui, sans-serif",
            fontWeight: 400,
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: "6px 10px",
            borderRadius: 8,
            transition: "all 0.2s ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "rgba(0, 51, 204, 0.6)";
            e.currentTarget.style.background = "rgba(0, 51, 204, 0.03)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "rgba(0, 51, 204, 0.28)";
            e.currentTarget.style.background = "none";
          }}
        >
          <Sparkles className="w-3 h-3" style={{ opacity: 0.7 }} />
          Query
        </motion.button>

      </motion.div>
    </div>
  );
}
