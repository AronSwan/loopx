import { useState } from "react";
import { ArrowLeft, Palette, Settings2 } from "lucide-react";

import type {
  WorkspaceGoal,
} from "./personal-workspace-model";
import { LarkSettingsPage } from "./lark-settings-page";

type WorkspaceSettingsTab = "lark" | "appearance";

const tabs: Array<{ description: string; icon: typeof Settings2; key: WorkspaceSettingsTab; label: string }> = [
  { description: "App、群聊和 Goal Topic 连接", icon: Settings2, key: "lark", label: "Lark" },
  { description: "主题和显示偏好", icon: Palette, key: "appearance", label: "外观" },
];

export function WorkspaceSettingsPage({
  focusGoalConnection = false,
  goals,
  initialGoalId,
  initialTab = "lark",
  onChanged,
  onClose,
  onThemeChange,
  theme,
}: {
  focusGoalConnection?: boolean;
  goals: WorkspaceGoal[];
  initialGoalId?: string | null;
  initialTab?: WorkspaceSettingsTab;
  onChanged: () => void;
  onClose: () => void;
  onThemeChange: (theme: "brutal" | "paper") => void;
  theme: "brutal" | "paper";
}) {
  const [tab, setTab] = useState<WorkspaceSettingsTab>(initialTab);

  return (
    <section aria-label="LoopX 设置" className="personal-settings-page" data-pw-theme={theme}>
      <aside className="personal-settings-sidebar">
        <button className="personal-settings-back" onClick={onClose} type="button">
          <ArrowLeft size={17} />
          <span>返回工作区</span>
        </button>
        <div className="personal-settings-title">
          <small>Settings</small>
          <strong>设置</strong>
        </div>
        <nav aria-label="设置分类" className="personal-settings-tabs">
          {tabs.map((item) => {
            const Icon = item.icon;
            return (
              <button aria-current={tab === item.key ? "page" : undefined} key={item.key} onClick={() => setTab(item.key)} type="button">
                <Icon size={17} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="personal-settings-body">
        <header className="personal-settings-header">
          <div>
            <small>{tab === "lark" ? "Goal connections" : "Workspace display"}</small>
            <h1>{tab === "lark" ? "Lark" : "外观"}</h1>
            <p>{tab === "lark" ? "管理可复用的 Lark App，并用独立 Topic 将群聊连接到 Goal。" : "管理当前浏览器里的工作区显示偏好。"}</p>
          </div>
        </header>
        {tab === "lark" ? (
          <LarkSettingsPage
            embedded
            focusGoalConnection={focusGoalConnection}
            goals={goals}
            initialGoalId={initialGoalId}
            onChanged={onChanged}
            onClose={onClose}
          />
        ) : null}

        {tab === "appearance" ? (
          <section className="personal-detail-card personal-appearance-settings">
            <small>Workspace display</small>
            <h3>外观</h3>
            <p>选择工作区的视觉风格。设置会保存在当前浏览器本地。</p>
            <div className="personal-settings-choice-group" role="radiogroup" aria-label="工作区主题">
              <button aria-checked={theme === "paper"} onClick={() => onThemeChange("paper")} role="radio" type="button">
                <span className="personal-settings-theme-swatch is-paper" />
                <strong>默认</strong>
                <small>安静、轻量，适合长期查看。</small>
              </button>
              <button aria-checked={theme === "brutal"} onClick={() => onThemeChange("brutal")} role="radio" type="button">
                <span className="personal-settings-theme-swatch is-brutal" />
                <strong>高对比</strong>
                <small>更强边框和更醒目的状态块。</small>
              </button>
            </div>
          </section>
        ) : null}
      </main>
    </section>
  );
}
