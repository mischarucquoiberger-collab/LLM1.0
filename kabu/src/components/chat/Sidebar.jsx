import React, { useState, useRef, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plus, MessageSquare, Trash2, PanelRightClose, PanelRight, Search, X } from "lucide-react";

function groupByTime(chats) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today - 86400000);
  const weekAgo = new Date(today - 7 * 86400000);
  const monthAgo = new Date(today - 30 * 86400000);

  const groups = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Previous 30 days", items: [] },
    { label: "Older", items: [] },
  ];

  for (const chat of chats) {
    const d = new Date(chat.updatedAt);
    if (d >= today) groups[0].items.push(chat);
    else if (d >= yesterday) groups[1].items.push(chat);
    else if (d >= weekAgo) groups[2].items.push(chat);
    else if (d >= monthAgo) groups[3].items.push(chat);
    else groups[4].items.push(chat);
  }

  return groups.filter(g => g.items.length > 0);
}

function chatTitle(chat) {
  if (chat.title) return chat.title;
  const firstUser = chat.messages?.find(m => m.role === "user");
  if (!firstUser) return "New conversation";
  const t = firstUser.content.trim();
  return t.length > 40 ? t.slice(0, 37) + "\u2026" : t;
}

const sidebarSpring = { type: "spring", stiffness: 350, damping: 28 };

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  isOpen,
  onToggle,
}) {
  const [search, setSearch] = useState("");
  const [hoveredId, setHoveredId] = useState(null);
  const [deletingIds, setDeletingIds] = useState(new Set());
  const searchRef = useRef(null);
  const deleteTimersRef = useRef([]);

  // Clean up delete timers on unmount
  useEffect(() => {
    return () => { deleteTimersRef.current.forEach(clearTimeout); };
  }, []);

  const filtered = search.trim()
    ? conversations.filter(c => chatTitle(c).toLowerCase().includes(search.toLowerCase()))
    : conversations;

  const groups = groupByTime(filtered);

  const handleDelete = useCallback((id) => {
    setDeletingIds(prev => new Set([...prev, id]));
    deleteTimersRef.current.push(setTimeout(() => {
      onDelete(id);
      setDeletingIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 300));
  }, [onDelete]);

  return (
    <>
      {/* Collapsed toggle */}
      <AnimatePresence>
        {!isOpen && (
          <motion.button
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 10 }}
            transition={{ duration: 0.15 }}
            onClick={onToggle}
            className="fixed top-4 right-4 z-50 w-9 h-9 rounded-xl bg-black/[0.04] ring-1 ring-black/[0.06] flex items-center justify-center hover:bg-black/[0.08] hover:ring-black/[0.12] transition-all duration-200"
          >
            <PanelRight className="w-4.5 h-4.5 text-black/40" />
          </motion.button>
        )}
      </AnimatePresence>

      {/* Panel */}
      <AnimatePresence>
        {isOpen && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 280, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={sidebarSpring}
            className="h-dvh shrink-0 overflow-hidden border-l border-black/[0.05] bg-white/80 backdrop-blur-2xl flex flex-col"
            style={{ maxWidth: "75vw" }}
          >
            <div className="flex flex-col h-full" style={{ width: "min(280px, 75vw)" }}>
              {/* Top bar */}
              <div className="flex items-center justify-between px-3.5 pt-4 pb-1">
                <button
                  onClick={onNew}
                  className="w-7 h-7 rounded-xl flex items-center justify-center hover:bg-black/[0.04] transition-all duration-200"
                  title="New chat"
                >
                  <Plus className="w-3.5 h-3.5 text-black/25" />
                </button>
                <button
                  onClick={onToggle}
                  className="w-7 h-7 rounded-xl flex items-center justify-center hover:bg-black/[0.04] transition-all duration-200"
                  title="Close sidebar"
                >
                  <PanelRightClose className="w-4 h-4 text-black/25" />
                </button>
              </div>

              {/* New chat button */}
              <div className="px-3 py-2">
                <button
                  onClick={onNew}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-black/[0.02] hover:bg-black/[0.05] ring-1 ring-black/[0.05] hover:ring-black/[0.1] transition-all duration-200 text-[13px] text-black/35 hover:text-black/60 group"
                >
                  <Plus className="w-3.5 h-3.5 transition-transform duration-200 group-hover:rotate-90" />
                  New chat
                </button>
              </div>

              {/* Search */}
              {conversations.length > 2 && (
                <div className="px-3 pb-2">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-black/15 pointer-events-none" />
                    <input
                      ref={searchRef}
                      value={search}
                      onChange={e => setSearch(e.target.value)}
                      placeholder="Search..."
                      className="w-full bg-black/[0.02] ring-1 ring-black/[0.05] rounded-xl pl-7 pr-7 py-2 text-[12px] text-black/60 placeholder-black/20 outline-none focus:ring-black/[0.1] focus:bg-black/[0.03] transition-all duration-200"
                    />
                    <AnimatePresence>
                      {search && (
                        <motion.button
                          initial={{ opacity: 0, scale: 0.8 }}
                          animate={{ opacity: 1, scale: 1 }}
                          exit={{ opacity: 0, scale: 0.8 }}
                          transition={{ duration: 0.1 }}
                          onClick={() => { setSearch(""); searchRef.current?.focus(); }}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-black/20 hover:text-black/40 transition-colors"
                        >
                          <X className="w-3 h-3" />
                        </motion.button>
                      )}
                    </AnimatePresence>
                  </div>
                </div>
              )}

              {/* Chat list */}
              <div className="flex-1 overflow-y-auto px-2 pb-4 sidebar-scroll">
                {groups.length === 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3 }}
                    className="flex flex-col items-center justify-center py-20"
                  >
                    <div className="w-10 h-10 rounded-2xl bg-black/[0.02] ring-1 ring-black/[0.05] flex items-center justify-center mb-3">
                      <MessageSquare className="w-4 h-4 text-black/10" />
                    </div>
                    <p className="text-[11px] text-black/20">
                      {search ? "No matching chats" : "No conversations yet"}
                    </p>
                  </motion.div>
                )}

                {groups.map(group => (
                  <div key={group.label} className="mb-0.5">
                    <div className="flex items-center gap-2 px-2.5 pt-5 pb-2">
                      <p className="text-[10px] text-black/15 uppercase tracking-[0.12em] font-medium whitespace-nowrap">
                        {group.label}
                      </p>
                      <div className="flex-1 h-px bg-black/[0.04]" />
                    </div>
                    <AnimatePresence mode="popLayout">
                      {group.items
                        .filter(c => !deletingIds.has(c.id))
                        .map(chat => {
                          const isActive = chat.id === activeId;
                          const isHovered = chat.id === hoveredId;
                          const title = chatTitle(chat);

                          return (
                            <motion.div
                              key={chat.id}
                              layout
                              initial={{ opacity: 0, x: 8 }}
                              animate={{ opacity: 1, x: 0 }}
                              exit={{
                                opacity: 0, x: 60, height: 0,
                                marginTop: 0, marginBottom: 0, paddingTop: 0, paddingBottom: 0,
                                transition: { duration: 0.25, ease: [0.4, 0, 0.2, 1] },
                              }}
                              transition={{ duration: 0.2 }}
                              onMouseEnter={() => setHoveredId(chat.id)}
                              onMouseLeave={() => setHoveredId(null)}
                              className="relative group mb-0.5"
                            >
                              <button
                                onClick={() => onSelect(chat.id)}
                                className={`w-full text-left pr-9 py-2.5 rounded-xl transition-all duration-200 flex items-center gap-0 ${
                                  isActive
                                    ? "bg-black/[0.05] text-black/70"
                                    : "text-black/35 hover:bg-black/[0.03] hover:text-black/55"
                                }`}
                              >
                                <div
                                  className={`w-[2.5px] shrink-0 rounded-full transition-all duration-300 ml-1 mr-2.5 ${
                                    isActive ? "h-4 bg-black/20" : "h-0 bg-transparent"
                                  }`}
                                />
                                <p className="text-[13px] leading-snug truncate flex-1">
                                  {title}
                                </p>
                              </button>

                              {/* Delete button */}
                              <div className={`absolute right-1.5 top-1/2 -translate-y-1/2 transition-opacity duration-150 ${
                                isHovered || isActive ? "opacity-100" : "opacity-0 pointer-events-none"
                              }`}>
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleDelete(chat.id); }}
                                  className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-red-500/10 transition-all duration-150"
                                >
                                  <Trash2 className="w-3 h-3 text-black/15 hover:text-red-500/70 transition-colors duration-150" />
                                </button>
                              </div>
                            </motion.div>
                          );
                        })}
                    </AnimatePresence>
                  </div>
                ))}
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      <style>{`
        .sidebar-scroll::-webkit-scrollbar { width: 3px; }
        .sidebar-scroll::-webkit-scrollbar-track { background: transparent; }
        .sidebar-scroll::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.04); border-radius: 3px; }
        .sidebar-scroll::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.08); }
      `}</style>
    </>
  );
}
