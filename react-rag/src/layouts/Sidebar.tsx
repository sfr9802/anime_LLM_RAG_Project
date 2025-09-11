import { useLocation, useNavigate } from "react-router-dom";
import "./Sidebar.css";

interface SidebarProps {
  collapsed: boolean;
}

const menuItems = [
  { path: "/", label: "메인", icon: "📌" },
  { path: "/settings", label: "설정", icon: "⚙️" },
];

export default function Sidebar({ collapsed }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();

  const currentPath = location.pathname;
  const isActive = (path: string) => currentPath === path;

  const handleNewChat = () => {
    // TODO: 새 채팅 로직
    navigate("/");
  };

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-header">{collapsed ? "💬" : "💬 Anime RAG"}</div>

      <nav className="chat-list">
        <button className="new-chat-btn" onClick={handleNewChat}>
          ＋{collapsed ? "" : " 새 채팅"}
        </button>

        <ul>
          {menuItems.map(({ path, label, icon }) => (
            <li key={path}>
              <button
                className={`chat-item ${isActive(path) ? "active" : ""}`}
                onClick={() => navigate(path)}
                title={label}
              >
                {icon} {collapsed ? "" : label}
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
