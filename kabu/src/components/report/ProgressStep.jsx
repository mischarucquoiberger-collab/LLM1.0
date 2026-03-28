import React from "react";
import { motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";

export default function ProgressStep({ step, index, currentStep }) {
  const isCompleted = index < currentStep;
  const isActive = index === currentStep;
  const isPending = index > currentStep;

  return (
    <motion.div
      className={`flex items-start gap-4 p-4 rounded-xl transition-all duration-500 ${
        isActive ? "bg-blue-500/[0.08] border border-blue-500/20" :
        isCompleted ? "bg-emerald-500/[0.04] border border-transparent" :
        "border border-transparent opacity-40"
      }`}
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: isPending ? 0.4 : 1, x: 0 }}
      transition={{ delay: index * 0.1, duration: 0.4 }}
    >
      <div className="shrink-0 mt-0.5">
        {isCompleted ? (
          <motion.div
            className="w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring", stiffness: 300 }}
          >
            <Check className="w-4 h-4 text-emerald-400" />
          </motion.div>
        ) : isActive ? (
          <div className="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center">
            <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
          </div>
        ) : (
          <div className="w-8 h-8 rounded-full bg-white/[0.05] flex items-center justify-center">
            <span className="text-xs text-gray-500 font-mono">{String(index + 1).padStart(2, "0")}</span>
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h4 className={`font-medium text-sm ${
            isActive ? "text-blue-300" : isCompleted ? "text-emerald-300" : "text-gray-500"
          }`}>
            {step.title}
          </h4>
          {isActive && (
            <motion.span
              className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 font-medium"
              animate={{ opacity: [1, 0.5, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              IN PROGRESS
            </motion.span>
          )}
          {isCompleted && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">
              DONE
            </span>
          )}
        </div>
        <p className={`text-xs mt-1 ${isActive ? "text-gray-400" : "text-gray-600"}`}>
          {step.description}
        </p>
      </div>

      <div className="shrink-0">
        <span className={`text-xs font-mono ${isActive ? "text-blue-400" : "text-gray-600"}`}>
          ~{step.duration}s
        </span>
      </div>
    </motion.div>
  );
}