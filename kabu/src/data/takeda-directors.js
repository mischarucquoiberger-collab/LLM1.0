/**
 * Takeda Pharmaceutical (4502) — Director Network Mock Data
 *
 * Based on real board composition as of 2025.
 * Includes historical data for timeline slider (2020-2025).
 */

// ── Director Nodes ──────────────────────────────────────────

export const DIRECTORS = [
  // ── Internal Directors ──
  {
    id: "weber",
    nameEn: "Christophe Weber",
    nameJp: "クリストフ ウェバー",
    role: "Representative Director, President & CEO",
    company: "Takeda",
    type: "internal",
    isIndependent: false,
    boardSeats: 1,
    university: "University of Lyon",
    universityJp: "リヨン大学",
    career: [
      { company: "GlaxoSmithKline", role: "VP Corporate Strategy → CEO GSK France → Head of Asia Pacific", years: "1993-2014" },
      { company: "Takeda", role: "COO → President & CEO", years: "2014-present" },
    ],
    otherBoards: [],
    committees: ["Nomination (Observer)"],
    joinYear: 2014,
    leaveYear: 2026,
    bio: "First non-Japanese CEO in Takeda's 240-year history. Led $62B acquisition of Shire in 2019.",
  },
  {
    id: "furuta",
    nameEn: "Milano Furuta",
    nameJp: "古田未来野",
    role: "Director, Chief Financial Officer",
    company: "Takeda",
    type: "internal",
    isIndependent: false,
    boardSeats: 1,
    university: "Wharton School (MBA), Hitotsubashi University",
    universityJp: "ウォートン・スクール / 一橋大学",
    career: [
      { company: "Mizuho Bank / IBJ", role: "Banking", years: "2000-2010" },
      { company: "Taiyo Pacific Partners", role: "Activist investment", years: "2008-2010" },
      { company: "Takeda", role: "Strategy → JPBU President → CFO", years: "2010-present" },
    ],
    otherBoards: [],
    committees: [],
    joinYear: 2024,
    leaveYear: null,
    bio: "Appointed CFO April 2024. Background in activist investing (Taiyo Pacific) before joining Takeda.",
  },
  {
    id: "plump",
    nameEn: "Andrew Plump",
    nameJp: null,
    role: "Director, President of R&D",
    company: "Takeda",
    type: "internal",
    isIndependent: false,
    boardSeats: 2,
    university: "MIT (BS), UCSF (MD), Rockefeller University (PhD)",
    universityJp: null,
    career: [
      { company: "Merck", role: "VP Worldwide Cardiovascular Research Head", years: "2004-2013" },
      { company: "Sanofi", role: "SVP Research & Translational Medicine", years: "2013-2015" },
      { company: "Takeda", role: "President R&D", years: "2015-present" },
    ],
    otherBoards: ["PhRMA Foundation (Chairman)"],
    committees: [],
    joinYear: 2015,
    leaveYear: null,
    bio: "MD/PhD physician-scientist. Led Takeda's R&D transformation and pipeline expansion.",
  },

  // ── External Independent Directors ──
  {
    id: "iijima",
    nameEn: "Masami Iijima",
    nameJp: "飯島彰己",
    role: "External Director, Chair of the Board",
    company: "Mitsui & Co.",
    type: "external",
    isIndependent: true,
    boardSeats: 3,
    university: "Yokohama National University",
    universityJp: "横浜国立大学",
    career: [
      { company: "Mitsui & Co.", role: "President & CEO → Chairman", years: "1974-2021" },
    ],
    otherBoards: ["SoftBank Group", "Kajima Corporation"],
    committees: ["Nomination (Chair)"],
    joinYear: 2018,
    leaveYear: null,
    bio: "Former CEO/Chairman of Mitsui & Co., core trading company of the Mitsui Group. Key keiretsu link.",
    keiretsuFlag: "Mitsui Group",
  },
  {
    id: "clark",
    nameEn: "Ian Clark",
    nameJp: null,
    role: "External Director",
    company: "Genentech (former CEO)",
    type: "external",
    isIndependent: true,
    boardSeats: 6,
    university: "University of Southampton",
    universityJp: null,
    career: [
      { company: "Sanofi", role: "Various roles", years: "1987-1995" },
      { company: "Novartis", role: "GM Canada → COO UK", years: "1995-2003" },
      { company: "Genentech", role: "SVP → CEO", years: "2003-2016" },
    ],
    otherBoards: ["Guardant Health", "GoodRx", "Kyverna Therapeutics", "Olema Pharma", "BioMarin"],
    committees: [],
    joinYear: 2018,
    leaveYear: null,
    bio: "Former CEO of Genentech. Prolific board member across US biotech.",
  },
  {
    id: "gillis",
    nameEn: "Steven Gillis",
    nameJp: null,
    role: "External Director",
    company: "ARCH Venture Partners",
    type: "external",
    isIndependent: true,
    boardSeats: 4,
    university: "Williams College, Dartmouth College (PhD)",
    universityJp: null,
    career: [
      { company: "Immunex Corporation", role: "Co-founder & CEO", years: "1981-1994" },
      { company: "Corixa Corp", role: "Co-founder & CEO → acquired by GSK", years: "1994-2005" },
      { company: "ARCH Venture Partners", role: "Managing Director", years: "2005-present" },
    ],
    otherBoards: ["HiberCell (CEO)", "eGenesis (Chairman)", "Vilya Inc (Founder)"],
    committees: ["Nomination"],
    joinYear: 2014,
    leaveYear: null,
    bio: "Pioneer immunologist, 300+ publications. Co-founded Immunex (Enbrel). Now leading biotech VC.",
  },
  {
    id: "higashi",
    nameEn: "Emiko Higashi",
    nameJp: "東恵美子",
    role: "External Director",
    company: "Tohmon Capital Partners",
    type: "external",
    isIndependent: true,
    boardSeats: 4,
    university: "International Christian University (Tokyo), Harvard Business School (MBA)",
    universityJp: "国際基督教大学 / ハーバード・ビジネス・スクール",
    career: [
      { company: "McKinsey & Co.", role: "Consultant (Tokyo)", years: "1983-1988" },
      { company: "Wasserstein Perella", role: "Founding member, Technology M&A", years: "1988-1994" },
      { company: "Merrill Lynch", role: "MD Global Technology M&A", years: "1994-2000" },
      { company: "Tohmon Capital Partners", role: "Founder & MD", years: "2003-present" },
    ],
    otherBoards: ["KLA Corporation", "Rambus Inc.", "Rapidus Corporation"],
    committees: ["Compensation (Chair)"],
    joinYear: 2019,
    leaveYear: null,
    bio: "Global M&A expert. Bridges Japanese and Silicon Valley corporate governance.",
  },
  {
    id: "maraganore",
    nameEn: "John Maraganore",
    nameJp: null,
    role: "External Director",
    company: "Alnylam Pharmaceuticals (former CEO)",
    type: "external",
    isIndependent: true,
    boardSeats: 4,
    university: "University of Chicago (BA, MS, PhD)",
    universityJp: null,
    career: [
      { company: "Biogen", role: "Director of Biological Research", years: "1987-1997" },
      { company: "Millennium Pharma", role: "SVP Strategic Product Development", years: "1997-2002" },
      { company: "Alnylam Pharmaceuticals", role: "Founding CEO", years: "2002-2021" },
      { company: "ARCH Venture Partners", role: "Venture Partner", years: "2021-present" },
    ],
    otherBoards: ["Beam Therapeutics", "Kymera Therapeutics", "Rapport Therapeutics"],
    committees: ["Compensation"],
    joinYear: 2022,
    leaveYear: null,
    bio: "Built Alnylam from scratch to first four approved RNAi therapeutics. Now active biotech investor.",
  },
  {
    id: "orsinger",
    nameEn: "Michel Orsinger",
    nameJp: null,
    role: "External Director",
    company: "DePuy Synthes / J&J (former)",
    type: "external",
    isIndependent: true,
    boardSeats: 1,
    university: "University of St. Gallen, Harvard Business School, INSEAD",
    universityJp: null,
    career: [
      { company: "Procter & Gamble", role: "Consumer goods", years: "1985-1995" },
      { company: "Novartis", role: "Division President, OTC", years: "1995-2006" },
      { company: "Synthes Inc.", role: "COO → CEO ($20B sale to J&J)", years: "2004-2012" },
      { company: "Johnson & Johnson", role: "Worldwide Chairman, DePuy Synthes", years: "2012-2015" },
    ],
    otherBoards: [],
    committees: ["Nomination", "Compensation"],
    joinYear: 2018,
    leaveYear: null,
    bio: "Led Synthes' $20B acquisition by J&J. Deep medtech and pharma operations expertise.",
  },
  {
    id: "tsusaka",
    nameEn: "Miki Tsusaka",
    nameJp: "津坂美樹",
    role: "External Director",
    company: "Microsoft Japan (President)",
    type: "external",
    isIndependent: true,
    boardSeats: 2,
    university: "Harvard University (BA), Harvard Business School (MBA)",
    universityJp: "ハーバード大学 / ハーバード・ビジネス・スクール",
    career: [
      { company: "Boston Consulting Group", role: "Senior Partner & MD → CMO → Executive Committee", years: "1990-2023" },
      { company: "Microsoft Japan", role: "President", years: "2023-present" },
    ],
    otherBoards: ["Microsoft Japan"],
    committees: ["Compensation"],
    joinYear: 2023,
    leaveYear: null,
    bio: "30+ year BCG veteran. Now leads Microsoft Japan. Strong marketing & digital transformation expertise.",
  },
  {
    id: "hatsukawa",
    nameEn: "Koji Hatsukawa",
    nameJp: "初川浩司",
    role: "External Director, Chair of Audit & Supervisory Committee",
    company: "PwC (former CEO)",
    type: "external",
    isIndependent: true,
    boardSeats: 2,
    university: "Keio University (BA Economics), Columbia Business School (MBA)",
    universityJp: "慶應義塾大学 / コロンビア・ビジネス・スクール",
    career: [
      { company: "Price Waterhouse", role: "Joined as CPA", years: "1974-1991" },
      { company: "ChuoAoyama PwC", role: "Representative Partner → CEO", years: "2000-2012" },
    ],
    otherBoards: ["Fujitsu Limited (Audit)"],
    committees: ["Audit (Chair)"],
    joinYear: 2019,
    leaveYear: null,
    bio: "Former CEO of PwC Japan (ChuoAoyama). CPA with deep audit and financial governance expertise.",
  },
  {
    id: "butel",
    nameEn: "Jean-Luc Butel",
    nameJp: null,
    role: "External Director, Audit & Supervisory Committee",
    company: "Medtronic (former EVP)",
    type: "external",
    isIndependent: true,
    boardSeats: 2,
    university: "George Washington University, Thunderbird School (MBA)",
    universityJp: null,
    career: [
      { company: "Johnson & Johnson", role: "Senior executive", years: "1985-1998" },
      { company: "Baxter International", role: "Corporate VP & President", years: "1998-2006" },
      { company: "Medtronic", role: "EVP & Group President International", years: "2006-2017" },
    ],
    otherBoards: ["Rani Therapeutics"],
    committees: ["Audit", "Nomination"],
    joinYear: 2020,
    leaveYear: null,
    bio: "30+ years in healthcare across Europe, Asia, Americas. Deep medtech international operations.",
  },
  {
    id: "fujimori",
    nameEn: "Yoshiaki Fujimori",
    nameJp: "藤森義明",
    role: "External Director, Audit & Supervisory Committee",
    company: "LIXIL Group (former CEO)",
    type: "external",
    isIndependent: true,
    boardSeats: 5,
    university: "University of Tokyo (BEng), Carnegie Mellon University (MBA)",
    universityJp: "東京大学 / カーネギーメロン大学",
    career: [
      { company: "General Electric", role: "Various → Chairman GE Japan", years: "1986-2011" },
      { company: "LIXIL Group", role: "President & CEO", years: "2011-2016" },
    ],
    otherBoards: ["Boston Scientific", "Shiseido", "Oracle Japan (Chairman)", "Toshiba"],
    committees: ["Audit", "Nomination"],
    joinYear: 2022,
    leaveYear: null,
    bio: "25 years at GE, then globalized LIXIL. Prolific board member — potential overboarding concern.",
  },
  {
    id: "reed",
    nameEn: "Kimberly Reed",
    nameJp: null,
    role: "External Director, Audit & Supervisory Committee",
    company: "Export-Import Bank of US (former CEO)",
    type: "external",
    isIndependent: true,
    boardSeats: 3,
    university: "West Virginia Wesleyan (BA), WVU College of Law (JD)",
    universityJp: null,
    career: [
      { company: "U.S. House of Representatives", role: "Counsel", years: "1997-2004" },
      { company: "U.S. Treasury", role: "Senior Advisor to Secretary", years: "2004-2007" },
      { company: "Lehman Brothers", role: "VP Financial Markets Policy", years: "2007-2008" },
      { company: "Export-Import Bank of US", role: "Chairman, President & CEO", years: "2019-2021" },
    ],
    otherBoards: ["Momentus Inc.", "Hannon Armstrong"],
    committees: ["Audit", "Compensation"],
    joinYear: 2022,
    leaveYear: null,
    bio: "First woman to lead US Ex-Im Bank. Deep government and financial policy expertise.",
  },

  // ── Historical Directors (for timeline) ──
  {
    id: "yamada",
    nameEn: "Tadataka Yamada",
    nameJp: "山田忠孝",
    role: "External Director (former)",
    company: "Gates Foundation (former President)",
    type: "external",
    isIndependent: true,
    boardSeats: 2,
    university: "Stanford University, NYU School of Medicine",
    universityJp: "スタンフォード大学",
    career: [
      { company: "University of Michigan", role: "Chairman of Internal Medicine", years: "1990-2000" },
      { company: "GlaxoSmithKline", role: "Chairman R&D", years: "2000-2006" },
      { company: "Bill & Melinda Gates Foundation", role: "President of Global Health", years: "2006-2011" },
      { company: "Takeda", role: "Chief Medical & Scientific Officer", years: "2015-2020" },
    ],
    otherBoards: ["Astellas Pharma (former)"],
    committees: [],
    joinYear: 2017,
    leaveYear: 2021,
    bio: "Japanese-American physician. Key architect of Takeda-Shire deal. Bridged Japanese & global pharma.",
  },
  {
    id: "iwasaki",
    nameEn: "Masato Iwasaki",
    nameJp: "岩崎真人",
    role: "Director, Japan Pharma Business (former)",
    company: "Takeda",
    type: "internal",
    isIndependent: false,
    boardSeats: 1,
    university: "Keio University",
    universityJp: "慶應義塾大学",
    career: [
      { company: "Takeda", role: "Japan Pharma Business Unit President → Director", years: "2000-2022" },
    ],
    otherBoards: [],
    committees: [],
    joinYear: 2018,
    leaveYear: 2022,
    bio: "Led Takeda's Japan pharmaceutical operations. Departed as part of board refresh.",
  },
];

// ── Connection Links ────────────────────────────────────────

export const CONNECTIONS = [
  // ── Board overlap (external boards) ──
  {
    source: "gillis", target: "maraganore",
    type: "board_overlap", weight: 5,
    detail: "Both Managing Director / Venture Partner at ARCH Venture Partners",
    startYear: 2022,
  },
  {
    source: "clark", target: "orsinger",
    type: "former_employer", weight: 3,
    detail: "Both held senior roles at Novartis",
    startYear: 2018,
  },
  {
    source: "orsinger", target: "butel",
    type: "former_employer", weight: 3,
    detail: "Both senior executives at Johnson & Johnson",
    startYear: 2020,
  },
  {
    source: "yamada", target: "weber",
    type: "former_employer", weight: 3,
    detail: "Both ex-GlaxoSmithKline executives",
    startYear: 2017,
    endYear: 2021,
  },
  {
    source: "plump", target: "gillis",
    type: "board_overlap", weight: 2,
    detail: "Connected through biotech R&D leadership circles",
    startYear: 2015,
  },

  // ── University connections ──
  {
    source: "higashi", target: "tsusaka",
    type: "university", weight: 3,
    detail: "Both Harvard University (BA) and Harvard Business School (MBA)",
    startYear: 2023,
  },
  {
    source: "hatsukawa", target: "iwasaki",
    type: "university", weight: 2,
    detail: "Both Keio University alumni",
    startYear: 2019,
    endYear: 2022,
  },
  {
    source: "hatsukawa", target: "fujimori",
    type: "university", weight: 1,
    detail: "Both Japanese elite university network (Keio / Tokyo University)",
    startYear: 2022,
  },

  // ── Committee connections ──
  {
    source: "iijima", target: "gillis",
    type: "committee", weight: 3,
    detail: "Nomination Committee: Iijima (Chair) + Gillis (Member)",
    startYear: 2018,
  },
  {
    source: "iijima", target: "orsinger",
    type: "committee", weight: 3,
    detail: "Nomination Committee: Iijima (Chair) + Orsinger (Member)",
    startYear: 2018,
  },
  {
    source: "iijima", target: "butel",
    type: "committee", weight: 2,
    detail: "Nomination Committee: Iijima (Chair) + Butel (Member)",
    startYear: 2020,
  },
  {
    source: "iijima", target: "fujimori",
    type: "committee", weight: 3,
    detail: "Nomination Committee: Iijima (Chair) + Fujimori (Member)",
    startYear: 2022,
  },
  {
    source: "higashi", target: "maraganore",
    type: "committee", weight: 2,
    detail: "Compensation Committee: Higashi (Chair) + Maraganore (Member)",
    startYear: 2022,
  },
  {
    source: "higashi", target: "orsinger",
    type: "committee", weight: 2,
    detail: "Compensation Committee: Higashi (Chair) + Orsinger (Member)",
    startYear: 2019,
  },
  {
    source: "higashi", target: "reed",
    type: "committee", weight: 2,
    detail: "Compensation Committee: Higashi (Chair) + Reed (Member)",
    startYear: 2022,
  },
  {
    source: "higashi", target: "tsusaka",
    type: "committee", weight: 2,
    detail: "Compensation Committee: Higashi (Chair) + Tsusaka (Member)",
    startYear: 2023,
  },
  {
    source: "hatsukawa", target: "butel",
    type: "committee", weight: 3,
    detail: "Audit & Supervisory Committee: Hatsukawa (Chair) + Butel (Member)",
    startYear: 2020,
  },
  {
    source: "hatsukawa", target: "fujimori",
    type: "committee", weight: 2,
    detail: "Audit Committee: Hatsukawa (Chair) + Fujimori (Member)",
    startYear: 2022,
  },
  {
    source: "hatsukawa", target: "reed",
    type: "committee", weight: 2,
    detail: "Audit Committee: Hatsukawa (Chair) + Reed (Member)",
    startYear: 2022,
  },
  {
    source: "butel", target: "fujimori",
    type: "committee", weight: 3,
    detail: "Both on Audit + Nomination committees — dual committee overlap",
    startYear: 2022,
  },

  // ── CEO / Chair governance link ──
  {
    source: "iijima", target: "weber",
    type: "advisor", weight: 4,
    detail: "Board Chair ↔ CEO governance relationship — closest oversight link",
    startYear: 2018,
  },

  // ── Internal executive links ──
  {
    source: "weber", target: "furuta",
    type: "board_overlap", weight: 4,
    detail: "CEO ↔ CFO executive leadership team at Takeda",
    startYear: 2024,
  },
  {
    source: "weber", target: "plump",
    type: "board_overlap", weight: 4,
    detail: "CEO ↔ R&D President executive leadership team at Takeda",
    startYear: 2015,
  },
  {
    source: "furuta", target: "plump",
    type: "board_overlap", weight: 3,
    detail: "CFO ↔ R&D President at Takeda",
    startYear: 2024,
  },

  // ── Keiretsu / Cross-corporate connections ──
  {
    source: "iijima", target: "fujimori",
    type: "advisor", weight: 2,
    detail: "Both leaders of major Japanese corporations — corporate Japan inner circle",
    startYear: 2022,
  },
  {
    source: "iijima", target: "furuta",
    type: "advisor", weight: 2,
    detail: "Board Chair oversight of new CFO — Iijima on Nomination Committee that approved Furuta",
    startYear: 2024,
  },
  {
    source: "iijima", target: "plump",
    type: "advisor", weight: 1,
    detail: "Board Chair oversight of R&D President",
    startYear: 2018,
  },

  // ── Consulting world ──
  {
    source: "higashi", target: "fujimori",
    type: "former_employer", weight: 1,
    detail: "Both McKinsey / consulting-trained with global corporate transformation background",
    startYear: 2022,
  },

  // ── Historical connections ──
  {
    source: "yamada", target: "plump",
    type: "board_overlap", weight: 3,
    detail: "Both Takeda R&D leadership — Yamada was CMSO, Plump was R&D President",
    startYear: 2017,
    endYear: 2021,
  },
  {
    source: "weber", target: "iwasaki",
    type: "board_overlap", weight: 3,
    detail: "CEO ↔ Japan Pharma Business Unit President at Takeda",
    startYear: 2018,
    endYear: 2022,
  },
];

// ── Connection type styles ──────────────────────────────────

export const CONNECTION_TYPES = {
  board_overlap:   { label: "Board Overlap",   color: "#3b82f6", dash: null,         defaultOn: true },
  former_employer: { label: "Former Employer",  color: "#a855f7", dash: [6, 4],       defaultOn: true },
  university:      { label: "University",       color: "#22d3ee", dash: [2, 3],       defaultOn: true },
  committee:       { label: "Committee",        color: "#f59e0b", dash: [8, 3, 2, 3], defaultOn: true },
  advisor:         { label: "Advisor/Governance",color: "#6b7280", dash: null,         defaultOn: true },
};

// ── Company color palette ───────────────────────────────────

export const COMPANY_COLORS = {
  "Takeda":                         "#e11d48",
  "Mitsui & Co.":                   "#f59e0b",
  "Genentech (former CEO)":         "#3b82f6",
  "ARCH Venture Partners":          "#8b5cf6",
  "Tohmon Capital Partners":        "#ec4899",
  "Alnylam Pharmaceuticals (former CEO)": "#10b981",
  "DePuy Synthes / J&J (former)":   "#06b6d4",
  "Microsoft Japan (President)":    "#0ea5e9",
  "PwC (former CEO)":               "#f97316",
  "Medtronic (former EVP)":         "#14b8a6",
  "LIXIL Group (former CEO)":       "#6366f1",
  "Export-Import Bank of US (former CEO)": "#64748b",
  "Gates Foundation (former President)":   "#84cc16",
};

// ── Cluster definitions (for convex hulls) ──────────────────

export const CLUSTERS = [
  {
    id: "takeda_exec",
    label: "Takeda Executive Core",
    members: ["weber", "furuta", "plump"],
    color: "rgba(225, 29, 72, 0.06)",
    borderColor: "rgba(225, 29, 72, 0.15)",
  },
  {
    id: "biotech_vc",
    label: "Biotech / VC Network",
    members: ["gillis", "maraganore", "clark"],
    color: "rgba(139, 92, 246, 0.06)",
    borderColor: "rgba(139, 92, 246, 0.15)",
  },
  {
    id: "nomination",
    label: "Nomination Committee",
    members: ["iijima", "gillis", "orsinger", "butel", "fujimori"],
    color: "rgba(245, 158, 11, 0.04)",
    borderColor: "rgba(245, 158, 11, 0.1)",
  },
  {
    id: "mitsui_link",
    label: "Potential Keiretsu Linkage: Mitsui Group",
    members: ["iijima", "fujimori"],
    color: "rgba(245, 158, 11, 0.08)",
    borderColor: "rgba(245, 158, 11, 0.2)",
  },
];

// ── Helper: compute independence fraud score ────────────────

const INSIDER_IDS = new Set(["weber", "furuta", "plump", "iwasaki"]);

export function computeIndependenceScore(directorId, connections, year = 2025) {
  const activeConns = connections.filter(c => {
    const matchDir = c.source === directorId || c.target === directorId;
    const inRange = (c.startYear || 0) <= year && (!c.endYear || c.endYear >= year);
    return matchDir && inRange;
  });

  const insiderConns = activeConns.filter(c => {
    const other = c.source === directorId ? c.target : c.source;
    return INSIDER_IDS.has(other);
  });

  const totalWeight = insiderConns.reduce((s, c) => s + (c.weight || 1), 0);

  return {
    totalConnections: activeConns.length,
    insiderConnections: insiderConns.length,
    insiderWeight: totalWeight,
    isFlagged: insiderConns.length >= 3,
    severity: insiderConns.length >= 4 ? "critical" : insiderConns.length >= 3 ? "warning" : "ok",
    details: insiderConns.map(c => ({
      insider: c.source === directorId ? c.target : c.source,
      type: c.type,
      detail: c.detail,
    })),
  };
}

// ── Helper: get data for a specific year ────────────────────

export function getDataForYear(year) {
  const nodes = DIRECTORS.filter(d => d.joinYear <= year && (!d.leaveYear || d.leaveYear > year));
  const nodeIds = new Set(nodes.map(n => n.id));
  const links = CONNECTIONS.filter(c => {
    const inRange = (c.startYear || 0) <= year && (!c.endYear || c.endYear > year);
    return inRange && nodeIds.has(c.source) && nodeIds.has(c.target);
  });
  return { nodes, links };
}
