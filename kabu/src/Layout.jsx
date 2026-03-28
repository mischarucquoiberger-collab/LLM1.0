import React from "react";

export default function Layout({ children }) {
  return (
    <div className="min-h-screen bg-[#0A0E1A]">
      {children}
    </div>
  );
}