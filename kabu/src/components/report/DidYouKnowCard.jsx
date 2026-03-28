import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Lightbulb } from "lucide-react";

const facts = [
  "Japan is the 4th largest stock market globally with over $6 trillion in market cap.",
  "Over 70% of TSE-listed companies have little to no English research coverage.",
  "The Tokyo Stock Exchange lists over 3,800 companies across multiple exchanges.",
  "Japanese companies hold some of the largest cash reserves in the world.",
  "The Nikkei 225 has outperformed the S&P 500 in recent years.",
  "Japan has more 100+ year old companies than any other country.",
  "Many Japanese small-caps trade below book value despite strong fundamentals.",
  "Cross-shareholding networks create hidden value opportunities in Japan.",
];

export default function DidYouKnowCard() {
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % facts.length);
    }, 6000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/[0.08] to-orange-500/[0.05] p-6 overflow-hidden relative">
      <div className="absolute top-0 right-0 w-32 h-32 bg-amber-500/10 rounded-full blur-3xl" />
      
      <div className="relative">
        <div className="flex items-center gap-2 mb-4">
          <motion.div
            animate={{ rotate: [0, 10, -10, 0] }}
            transition={{ duration: 2, repeat: Infinity, repeatDelay: 4 }}
          >
            <Lightbulb className="w-5 h-5 text-amber-400" />
          </motion.div>
          <h3 className="text-amber-300 font-semibold text-sm">Did you know?</h3>
        </div>

        <AnimatePresence mode="wait">
          <motion.p
            key={currentIndex}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.4 }}
            className="text-gray-300 text-sm leading-relaxed"
          >
            {facts[currentIndex]}
          </motion.p>
        </AnimatePresence>

        <div className="flex gap-1.5 mt-4">
          {facts.map((_, i) => (
            <div
              key={i}
              className={`h-1 rounded-full transition-all duration-300 ${
                i === currentIndex ? "bg-amber-400 w-8" : "bg-amber-500/20 w-1.5"
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}