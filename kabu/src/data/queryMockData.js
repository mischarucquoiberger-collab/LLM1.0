export const FEATURE_CATEGORIES = {
  shareholderVoting: {
    label: "Shareholder Voting",
    accent: "rose",
    icon: "Vote",
  },
  directorProposals: {
    label: "Director Proposals",
    accent: "teal",
    icon: "UserCheck",
  },
  hiddenRealEstate: {
    label: "Hidden Real Estate",
    accent: "amber",
    icon: "Building",
  },
  directorCorrelation: {
    label: "Director Correlation",
    accent: "purple",
    icon: "Network",
  },
  research: {
    label: "Research",
    accent: "blue",
    icon: "FileSearch",
  },
};

export const ACCENT_COLORS = {
  rose: {
    dot: "bg-rose-400",
    badge: "bg-rose-500/15 text-rose-300 border-rose-500/20",
    highlight: "text-rose-400",
    card: "border-rose-500/20 bg-rose-500/5",
  },
  teal: {
    dot: "bg-teal-400",
    badge: "bg-teal-500/15 text-teal-300 border-teal-500/20",
    highlight: "text-teal-400",
    card: "border-teal-500/20 bg-teal-500/5",
  },
  amber: {
    dot: "bg-amber-400",
    badge: "bg-amber-500/15 text-amber-300 border-amber-500/20",
    highlight: "text-amber-400",
    card: "border-amber-500/20 bg-amber-500/5",
  },
  purple: {
    dot: "bg-purple-400",
    badge: "bg-purple-500/15 text-purple-300 border-purple-500/20",
    highlight: "text-purple-400",
    card: "border-purple-500/20 bg-purple-500/5",
  },
  blue: {
    dot: "bg-blue-400",
    badge: "bg-blue-500/15 text-blue-300 border-blue-500/20",
    highlight: "text-blue-400",
    card: "border-blue-500/20 bg-blue-500/5",
  },
};

export const MOCK_QUERIES = [
  {
    id: "shareholder-low-support",
    query: "Companies with lowest shareholder proposal support",
    pattern: "lowest shareholder",
    featureCategory: "shareholderVoting",
    resultType: "table",
    results: [
      { ticker: "7203", company: "Toyota Motor", metric: "12.3%", metricLabel: "Avg Support", detail: "8 proposals below 20% threshold" },
      { ticker: "6758", company: "Sony Group", metric: "15.7%", metricLabel: "Avg Support", detail: "5 proposals below 20% threshold" },
      { ticker: "9984", company: "SoftBank Group", metric: "18.2%", metricLabel: "Avg Support", detail: "6 proposals below 20% threshold" },
      { ticker: "8306", company: "Mitsubishi UFJ", metric: "21.4%", metricLabel: "Avg Support", detail: "3 proposals below 20% threshold" },
      { ticker: "6861", company: "Keyence Corp", metric: "22.8%", metricLabel: "Avg Support", detail: "2 proposals below 20% threshold" },
    ],
  },
  {
    id: "director-low-approval",
    query: "Directors with lowest approval % in last 6 months",
    pattern: "lowest approval",
    featureCategory: "directorProposals",
    resultType: "table",
    results: [
      { ticker: "7751", company: "Canon Inc", metric: "52.1%", metricLabel: "Approval", detail: "Director: Fujio Mitarai — re-election vote" },
      { ticker: "9984", company: "SoftBank Group", metric: "58.3%", metricLabel: "Approval", detail: "Director: Masayoshi Son — compensation vote" },
      { ticker: "7203", company: "Toyota Motor", metric: "61.7%", metricLabel: "Approval", detail: "Director: Akio Toyoda — re-election vote" },
      { ticker: "6752", company: "Panasonic Holdings", metric: "64.2%", metricLabel: "Approval", detail: "Director: Yuki Kusumi — strategy mandate" },
      { ticker: "8058", company: "Mitsubishi Corp", metric: "67.9%", metricLabel: "Approval", detail: "Director: Katsuya Nakanishi — audit committee" },
    ],
  },
  {
    id: "hidden-realestate",
    query: "Companies with hidden real estate value over ¥10B",
    pattern: "hidden real estate",
    featureCategory: "hiddenRealEstate",
    resultType: "cards",
    results: [
      { ticker: "8801", company: "Mitsui Fudosan", bookValue: "¥284B", marketValue: "¥892B", hiddenValue: "¥608B", location: "Nihonbashi, Tokyo — 12 properties" },
      { ticker: "8802", company: "Mitsubishi Estate", bookValue: "¥312B", marketValue: "¥745B", hiddenValue: "¥433B", location: "Marunouchi, Tokyo — 9 properties" },
      { ticker: "9020", company: "JR East", bookValue: "¥156B", marketValue: "¥478B", hiddenValue: "¥322B", location: "Station-adjacent land — 34 sites" },
      { ticker: "9022", company: "JR Central", bookValue: "¥89B", marketValue: "¥267B", hiddenValue: "¥178B", location: "Nagoya–Tokyo corridor — 18 sites" },
      { ticker: "8830", company: "Sumitomo Realty", bookValue: "¥198B", marketValue: "¥341B", hiddenValue: "¥143B", location: "Shinjuku, Tokyo — 7 properties" },
      { ticker: "3289", company: "Tokyu Fudosan", bookValue: "¥72B", marketValue: "¥185B", hiddenValue: "¥113B", location: "Shibuya, Tokyo — 5 properties" },
    ],
  },
  {
    id: "director-interlocks",
    query: "Director interlocks between Toyota and SoftBank",
    pattern: "interlocks",
    featureCategory: "directorCorrelation",
    resultType: "network",
    results: [
      { name: "Takeshi Uchiyamada", roleA: "Toyota Motor — Chairman", roleB: "SoftBank Vision Fund — Advisory Board", sharedBoards: ["JAMA", "Keidanren Digital Council"] },
      { name: "Yuko Kawamoto", roleA: "Toyota Motor — Independent Director", roleB: "SoftBank Group — Audit Committee", sharedBoards: ["Japan Corporate Governance Forum"] },
      { name: "Hiroshi Mikitani", roleA: "Toyota Connected — Advisor", roleB: "SoftBank Group — Board Observer", sharedBoards: ["New Economy Summit", "Japan Association of Corporate Executives"] },
    ],
  },
  {
    id: "activist-governance",
    query: "Companies where activists proposed governance changes",
    pattern: "activist",
    featureCategory: "shareholderVoting",
    resultType: "table",
    results: [
      { ticker: "4502", company: "Takeda Pharma", metric: "3 proposals", metricLabel: "Activist Items", detail: "Elliott Management — board composition reform" },
      { ticker: "9984", company: "SoftBank Group", metric: "5 proposals", metricLabel: "Activist Items", detail: "Third Point — capital allocation review" },
      { ticker: "7752", company: "Ricoh Co", metric: "2 proposals", metricLabel: "Activist Items", detail: "ValueAct Capital — strategic review" },
      { ticker: "6857", company: "Advantest Corp", metric: "2 proposals", metricLabel: "Activist Items", detail: "Oasis Management — ROE improvement" },
      { ticker: "8604", company: "Nomura Holdings", metric: "4 proposals", metricLabel: "Activist Items", detail: "Effissimo Capital — cross-shareholding unwinding" },
    ],
  },
  {
    id: "multi-board-directors",
    query: "Board members serving on 3+ public company boards",
    pattern: "3+ boards",
    featureCategory: "directorCorrelation",
    resultType: "table",
    results: [
      { ticker: "—", company: "Multiple", metric: "5 boards", metricLabel: "Board Seats", detail: "Nobuyuki Idei — Sony, Accenture Japan, Lenovo, Cloudera, FreakOut" },
      { ticker: "—", company: "Multiple", metric: "4 boards", metricLabel: "Board Seats", detail: "Yuko Kawamoto — Toyota, SoftBank, Hitachi, Waseda University" },
      { ticker: "—", company: "Multiple", metric: "4 boards", metricLabel: "Board Seats", detail: "George Olcott — Dentsu, Komatsu, Nikkei, JSR Corp" },
      { ticker: "—", company: "Multiple", metric: "3 boards", metricLabel: "Board Seats", detail: "Christina Ahmadjian — Mitsubishi Heavy, ORIX, Japan Post" },
      { ticker: "—", company: "Multiple", metric: "3 boards", metricLabel: "Board Seats", detail: "Nicholas Benes — JTP, BDTI, Symantec Japan" },
    ],
  },
];
