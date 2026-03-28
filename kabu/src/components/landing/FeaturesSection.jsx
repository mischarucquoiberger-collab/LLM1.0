import React from "react";
import { motion } from "framer-motion";
import { Brain, Shield, Zap, BarChart3, Globe, Lock } from "lucide-react";

const features = [
  {
    icon: Brain,
    title: "AI Deep Analysis",
    description: "Our models analyze financial statements, news sentiment, and market data to generate comprehensive reports.",
    color: "blue",
  },
  {
    icon: Shield,
    title: "Hidden Insights",
    description: "Discover under-the-radar information that institutional investors use but rarely share publicly.",
    color: "amber",
  },
  {
    icon: Zap,
    title: "Real-Time Speed",
    description: "Reports generated in under 4 minutes. No waiting days for analyst coverage.",
    color: "cyan",
  },
  {
    icon: BarChart3,
    title: "Quantitative Scoring",
    description: "Proprietary scoring system rates companies across 40+ fundamental and technical factors.",
    color: "emerald",
  },
  {
    icon: Globe,
    title: "Japan Specialist",
    description: "Built specifically for Japanese markets — TSE, JASDAQ, Mothers, and more.",
    color: "purple",
  },
  {
    icon: Lock,
    title: "Institutional Grade",
    description: "Same depth of analysis used by hedge funds and asset managers, now accessible to everyone.",
    color: "rose",
  },
];

const colorMap = {
  blue: "from-blue-500/20 to-blue-600/5 text-blue-400 border-blue-500/20",
  amber: "from-amber-500/20 to-amber-600/5 text-amber-400 border-amber-500/20",
  cyan: "from-cyan-500/20 to-cyan-600/5 text-cyan-400 border-cyan-500/20",
  emerald: "from-emerald-500/20 to-emerald-600/5 text-emerald-400 border-emerald-500/20",
  purple: "from-purple-500/20 to-purple-600/5 text-purple-400 border-purple-500/20",
  rose: "from-rose-500/20 to-rose-600/5 text-rose-400 border-rose-500/20",
};

export default function FeaturesSection() {
  return (
    <section className="relative py-32 bg-[#0A0E1A]">
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          className="text-center mb-20"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
        >
          <h2 className="text-4xl sm:text-5xl font-bold text-white mb-4">
            Why <span className="text-blue-400">this platform</span>
          </h2>
          <p className="text-gray-400 text-lg max-w-xl mx-auto">
            Institutional-quality research, powered by AI, built for Japan.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature, i) => {
            const Icon = feature.icon;
            const colors = colorMap[feature.color];
            return (
              <motion.div
                key={feature.title}
                className="group relative p-8 rounded-2xl border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04] transition-all duration-500"
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
              >
                <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${colors} border flex items-center justify-center mb-5`}>
                  <Icon className="w-6 h-6" />
                </div>
                <h3 className="text-xl font-semibold text-white mb-3">{feature.title}</h3>
                <p className="text-gray-400 leading-relaxed text-sm">{feature.description}</p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
