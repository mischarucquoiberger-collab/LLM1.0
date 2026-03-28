import React from "react";
import { motion } from "framer-motion";
import { Check, Loader2, Clock } from "lucide-react";

export default function PipelineStep({ step, status, index }) {
  return (
    <motion.div
      className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 ${
        status === "active" ? "bg-blue-500/10 border border-blue-500/30" :
        status === "done" ? "bg-emerald-500/5 border border-emerald-500/20" :
        "border border-white/5 opacity-50"
      }`}
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: status === "queued" ? 0.5 : 1, x: 0 }}
      transition={{ delay: index * 0.05 }}
    >
      <div className="shrink-0">
        {status === "done" ? (
          <motion.div
            initial={{ scale: 0, rotate: -180 }}
            animate={{ scale: 1, rotate: 0 }}
            transition={{ type: "spring", stiffness: 200 }}
            className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center"
          >
            <Check className="w-3.5 h-3.5 text-emerald-400" />
          </motion.div>
        ) : status === "active" ? (
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center"
          >
            <Loader2 className="w-3.5 h-3.5 text-blue-400" />
          </motion.div>
        ) : (
          <div className="w-6 h-6 rounded-full bg-white/5 flex items-center justify-center">
            <Clock className="w-3.5 h-3.5 text-gray-600" />
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium ${
          status === "active" ? "text-blue-300" :
          status === "done" ? "text-emerald-300" :
          "text-gray-500"
        }`}>
          {step.title}
        </p>
      </div>

      {status === "active" && (
        <motion.div
          animate={{ opacity: [1, 0.5, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
          className="shrink-0"
        >
          <span className="text-xs px-2 py-1 rounded-full bg-blue-500/20 text-blue-400 font-medium">
            ACTIVE
          </span>
        </motion.div>
      )}

      {status === "done" && (
        <span className="text-xs px-2 py-1 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">
          DONE
        </span>
      )}
    </motion.div>
  );
}