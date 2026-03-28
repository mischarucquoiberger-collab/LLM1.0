import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Download, Share2, X, Home, ExternalLink } from "lucide-react";

export default function CompletionModal({ 
  isOpen, 
  onClose, 
  companyName, 
  onView,
  onDownload,
  onShare,
  onHome
}) {
  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ type: "spring", duration: 0.5 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md z-50"
          >
            <div className="bg-[#12162a] rounded-3xl border border-white/10 p-8 relative overflow-hidden shadow-2xl">
              <div className="absolute top-0 right-0 w-40 h-40 bg-emerald-500/10 rounded-full blur-3xl" />

              <button
                onClick={onHome}
                className="absolute top-4 left-4 text-gray-500 hover:text-white transition-colors inline-flex items-center gap-1 text-xs"
              >
                <Home className="w-4 h-4" />
                Home
              </button>

              <button
                onClick={onClose}
                className="absolute top-4 right-4 text-gray-500 hover:text-gray-300 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>

              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
                className="w-16 h-16 rounded-2xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center mx-auto mb-6"
              >
                <CheckCircle2 className="w-8 h-8 text-emerald-400" />
              </motion.div>

              <motion.h2
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
                className="text-2xl font-bold text-white text-center mb-2"
              >
                Report Complete!
              </motion.h2>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.4 }}
                className="text-gray-400 text-center mb-8"
              >
                Your comprehensive analysis for <span className="text-blue-400 font-medium">{companyName}</span> is ready to view.
              </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
                className="space-y-3"
              >
                <button
                onClick={onView}
                className="w-full py-3.5 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-blue-400 text-white rounded-xl font-semibold transition-all shadow-lg shadow-blue-600/25 flex items-center justify-center gap-2"
              >
                View Full Report
                <ExternalLink className="w-4 h-4" />
              </button>
                
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={onDownload}
                    className="py-2.5 border border-white/10 hover:border-white/20 text-gray-300 hover:text-white rounded-xl font-medium transition-all flex items-center justify-center gap-2 text-sm"
                  >
                    <Download className="w-4 h-4" />
                    Download
                  </button>
                  <button
                    onClick={onShare}
                    className="py-2.5 border border-white/10 hover:border-white/20 text-gray-300 hover:text-white rounded-xl font-medium transition-all flex items-center justify-center gap-2 text-sm"
                  >
                    <Share2 className="w-4 h-4" />
                    Share
                  </button>
                </div>
              </motion.div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
