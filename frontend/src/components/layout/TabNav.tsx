import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import {
  Gauge,
  ClipboardList,
  GitBranch,
  Lightbulb,
  Bug,
  Palette,
  Files,
  BookOpen,
  Crosshair,
  Settings,
} from 'lucide-react';
import { useEffect } from 'react';
import { useAppContext } from '@/context/AppContext';

export const TABS = [
  { id: 'overview', label: 'Overview', icon: Gauge, key: '`', path: '/overview' },
  { id: 'picks', label: 'Picks', icon: Crosshair, key: '1', path: '/picks' },
  { id: 'plans', label: 'Plans', icon: ClipboardList, key: '2', path: '/plans' },
  { id: 'workflow', label: 'Workflow', icon: GitBranch, key: '3', path: '/workflow' },
  { id: 'ideation', label: 'Ideation', icon: Lightbulb, key: '4', path: '/ideation' },
  { id: 'debug', label: 'Debug', icon: Bug, key: '5', path: '/debug' },
  { id: 'designs', label: 'Designs', icon: Palette, key: '6', path: '/designs' },
  { id: 'documents', label: 'Documents', icon: Files, key: '7', path: '/documents' },
  { id: 'memory', label: 'Memory', icon: BookOpen, key: 'i', path: '/memory/intents' },
  { id: 'settings', label: 'Settings', icon: Settings, key: '8', path: '/settings' },
];

export function TabNav({
  onToggleShortcuts,
}: {
  onToggleShortcuts: () => void;
}) {
  const { theme, setTheme } = useAppContext();
  const navigate = useNavigate();
  const location = useLocation();

  const isMemoryActive = location.pathname.startsWith('/memory');

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName || '')) return;

      if (e.key === '?') {
        onToggleShortcuts();
        return;
      }
      if (e.key === 't' || e.key === 'T') {
        setTheme(theme === 'dark' ? 'light' : 'dark');
        return;
      }

      const tab = TABS.find(t => t.key === e.key);
      if (tab) {
        navigate(tab.path);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [navigate, onToggleShortcuts, setTheme, theme]);

  return (
    <div className="bg-background border-b px-6 flex flex-col">
      <nav className="bg-transparent h-12 flex gap-6 p-0 items-center overflow-x-auto">
        {TABS.map((tab) => (
          <NavLink
            key={tab.id}
            to={tab.path}
            end={tab.id === 'plans'}
            className={({ isActive }) =>
              `flex items-center h-full px-2 gap-2 rounded-none transition-colors border-b-2 whitespace-nowrap ${
                isActive || (tab.id === 'memory' && isMemoryActive)
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`
            }
          >
            <tab.icon className="h-4 w-4" />
            <span>{tab.label}</span>
            <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded opacity-50">{tab.key}</span>
          </NavLink>
        ))}
      </nav>
      {isMemoryActive && (
        <nav className="bg-transparent h-10 flex gap-6 p-0 items-center overflow-x-auto border-t border-muted">
          <NavLink
            to="/memory/intents"
            className={({ isActive }) =>
              `flex items-center h-full px-2 gap-2 rounded-none transition-colors border-b-2 whitespace-nowrap ${
                isActive ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
              }`
            }
          >
            Intents
          </NavLink>
          <NavLink
            to="/memory/fact-checks"
            className={({ isActive }) =>
              `flex items-center h-full px-2 gap-2 rounded-none transition-colors border-b-2 whitespace-nowrap ${
                isActive ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
              }`
            }
          >
            Fact-Check
          </NavLink>
          <NavLink
            to="/memory/references"
            className={({ isActive }) =>
              `flex items-center h-full px-2 gap-2 rounded-none transition-colors border-b-2 whitespace-nowrap ${
                isActive ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
              }`
            }
          >
            Reference
          </NavLink>
        </nav>
      )}
    </div>
  );
}
