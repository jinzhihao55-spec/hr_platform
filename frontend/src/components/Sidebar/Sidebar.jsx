import { useEffect, useState } from 'react';
import {
  CalendarDays,
  FileClock,
  FileSpreadsheet,
  History,
  Menu,
  Settings,
  SquareActivity,
  X,
} from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import './Sidebar.css';

const navItems = [
  { to: '/calendar', icon: CalendarDays, label: '运行日历' },
  { to: '/reports/daily', icon: FileSpreadsheet, label: '日报' },
  { to: '/reports/weekly', icon: FileClock, label: '周报' },
  { to: '/system', icon: SquareActivity, label: '系统状态' },
  { to: '/history', icon: History, label: '历史归档' },
  { to: '/settings', icon: Settings, label: '设置' },
];

export default function Sidebar() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  return (
    <>
      <button
        type="button"
        className={`mobile-nav-trigger ${open ? 'open' : ''}`}
        aria-label={open ? '关闭导航' : '打开导航'}
        aria-expanded={open}
        aria-controls="primary-navigation"
        title={open ? '关闭导航' : '打开导航'}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <X aria-hidden="true" size={20} /> : <Menu aria-hidden="true" size={20} />}
      </button>
      {open && (
        <button
          type="button"
          className="mobile-nav-backdrop"
          aria-label="关闭导航"
          onClick={() => setOpen(false)}
        />
      )}
      <aside id="primary-navigation" className={`side ${open ? 'open' : ''}`}>
        <div className="logo">
          <div className="mk">人</div>
          <div>
            <b>人事报表智能体</b>
            <span>HR Report Agent</span>
          </div>
        </div>
        <nav className="nav" aria-label="主导航">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => (
                isActive
                  ? 'active'
                  : ''
              )}
            >
              <Icon className="i" aria-hidden="true" size={17} strokeWidth={1.8} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="foot">
          单机运行 · 数据留在本地
          <br />
          确定性 · 可追溯 · 不臆测
        </div>
      </aside>
    </>
  );
}
