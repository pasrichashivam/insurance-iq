import { useState } from "react";
import { Upload, MessageSquare, ShieldCheck, Monitor, Bot, ClipboardCheck, Database } from "lucide-react";
import DataExplorerTab from "@/components/DataExplorerTab";
import DocumentUploadTab from "@/components/DocumentUploadTab";
import RagQATab from "@/components/RagQATab";
import AuditTab from "@/components/AuditTab";
import UnderwriterTab from "@/components/UnderwriterTab";
import AssistantTab from "@/components/AssistantTab";
import SystemStatusTab from "@/components/SystemStatusTab";

const TABS = [
  
  { id: "qa", label: "Policy Q&A (RAG)", icon: MessageSquare },
  { id: "assistant", label: "Insurance Assistant", icon: Bot },
  { id: "explorer", label: "Data Explorer", icon: Database },
  { id: "audit", label: "Claims Review", icon: ShieldCheck },
  { id: "underwriting", label: "Underwriter Navigator", icon: ClipboardCheck },
  { id: "upload", label: "Index Documents", icon: Upload },
  { id: "status", label: "System Status", icon: Monitor },
  
] as const;

type TabId = (typeof TABS)[number]["id"];

const Index = () => {
  const [activeTab, setActiveTab] = useState<TabId>("upload");
  const activeTabDetails = TABS.find((tab) => tab.id === activeTab)!;
  const ActiveTabIcon = activeTabDetails.icon;

  return (
    <div className="app-shell min-h-screen flex">
      {/* Sidebar */}
      <aside className="app-sidebar w-[260px] shrink-0 border-r border-border/70 backdrop-blur-xl flex flex-col">
        {/* Logo */}
        <div className="px-5 pt-6 pb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary via-fuchsia-500 to-accent flex items-center justify-center text-[11px] font-extrabold text-primary-foreground shrink-0 font-heading shadow-lg shadow-primary/30 ring-1 ring-white/20">
              I-IQ
            </div>
            <div>
              <h1 className="text-sm font-bold font-heading text-foreground tracking-tight leading-tight">
                Insurance-IQ
              </h1>
              <p className="text-[10px] text-muted-foreground leading-tight">
                Insurance Intelligence Platform
              </p>
            </div>
          </div>
        </div>

        {/* Section label */}
        <div className="px-5 pt-2 pb-2">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">Platform</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 space-y-0.5">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`group w-full flex items-center gap-3.5 px-4 py-3.5 rounded-lg text-sm font-medium transition-all relative
                  ${isActive
                    ? "bg-gradient-to-r from-primary/20 to-accent/15 text-foreground font-semibold shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-white/5"
                  }`}
              >
                {isActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-7 rounded-r-full bg-gradient-to-b from-primary to-accent shadow-[0_0_12px_hsl(var(--primary))]" />
                )}
                <span className={`flex items-center justify-center w-9 h-9 rounded-lg transition-colors
                  ${isActive ? "bg-primary/20 text-primary" : "bg-muted/50 group-hover:bg-white/10"}`}>
                  <Icon className="w-[18px] h-[18px] shrink-0" />
                </span>
                {tab.label}
              </button>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-border/50 mx-3 mb-2">
          <p className="text-[10px] text-muted-foreground/50 text-center tracking-wide">Cardinal Ridge Insurance Group · Columbus, OH (fictional demo company)</p>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <header className="workspace-header mb-8 rounded-2xl px-6 py-5 sm:px-7">
            <div className="relative z-10 flex items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent text-primary-foreground shadow-lg shadow-primary/25">
                  <ActiveTabIcon className="h-5 w-5" />
                </div>
                <div>
                  <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.22em] text-primary">Cardinal Ridge</p>
                  <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">{activeTabDetails.label}</h2>
                </div>
              </div>
              <div className="hidden rounded-full border border-primary/25 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary sm:block">
                Insurance Intelligence
              </div>
            </div>
          </header>
          {activeTab === "upload" && <DocumentUploadTab />}
          {activeTab === "qa" && <RagQATab />}
          {activeTab === "assistant" && <AssistantTab />}
          {activeTab === "explorer" && <DataExplorerTab />}
          {activeTab === "audit" && <AuditTab />}
          {activeTab === "underwriting" && <UnderwriterTab />}
          {activeTab === "status" && <SystemStatusTab />}
        </div>
      </main>
    </div>
  );
};

export default Index;
