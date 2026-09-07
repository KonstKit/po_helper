import React, { useState, useMemo } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  AppBar,
  Box,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Divider,
  Avatar,
  Menu,
  MenuItem,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard as DashboardIcon,
  Folder as FolderIcon,
  Assignment as AssignmentIcon,
  Analytics as AnalyticsIcon,
  GppGood as QualityIcon,
  Settings as SettingsIcon,
  MenuBook as KnowledgeIcon,
  Science as TestingIcon,
  Logout as LogoutIcon,
  Person as PersonIcon,
  AccountTree as TraceabilityIcon,
  Tune as JiraFieldsIcon,
  AccountTreeOutlined as RuleBuilderIcon,
  History as HistoryIcon,
  BubbleChart as VisualizationIcon,
  ExpandLess,
  ExpandMore,
  Speed as SprintCapacityIcon,
  MonitorHeart as SyncHealthIcon,
} from '@mui/icons-material';
import { Collapse, Stack } from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import { performLogout } from '../utils/logout';
import { readStoredJson, writeStoredJson } from '../utils/browserStorage';
import ProjectSelector from './common/ProjectSelector';
import type { RootState } from '../store/store';

const drawerWidth = 240;

// Canonical page titles for the header (UX review M1/M2): one vocabulary shared
// with the sidebar, so the header title always matches where the user is.
const ROUTE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/projects': 'Projects',
  '/tasks': 'Tasks',
  '/analytics': 'Analytics',
  '/sprint-capacity': 'Sprint Capacity',
  '/knowledge': 'Knowledge',
  '/traceability': 'Traceability',
  '/traceability/visualization': 'D3 Visualization',
  '/traceability/flow-builder': 'Rule Builder',
  '/traceability/rules': 'Rules',
  '/traceability/review': 'Review Queue',
  '/traceability/history': 'Execution History',
  '/quality': 'Quality',
  '/testing': 'Test Results',
  '/jira-fields': 'Jira Fields',
  '/settings': 'Settings',
  '/profile': 'Profile',
};

// The header project selector is shown ONLY on routes that actually consume the
// global selection (codex P2). Showing it elsewhere (Quality, Tasks, Sprint
// Capacity, Project Details, Knowledge) was misleading: those pages keep their
// own/local project state, so changing it in the header did nothing visible.
// Dashboard ('/') is handled as an exact match in `showProjectSelector` below.
const PROJECT_SELECTOR_ROUTES = ['/analytics', '/traceability/visualization', '/traceability/review'];

function resolveRouteTitle(pathname: string): string {
  if (/^\/projects\/[^/]+/.test(pathname)) return 'Project Details';
  const keys = Object.keys(ROUTE_TITLES).sort((a, b) => b.length - a.length);
  for (const k of keys) {
    if (pathname === k || (k !== '/' && pathname.startsWith(k + '/')) || pathname.startsWith(k)) {
      if (k === '/' && pathname !== '/') continue;
      return ROUTE_TITLES[k];
    }
  }
  return 'PO Helper';
}

interface NavigationItem {
  text: string;
  icon: React.ReactNode;
  path: string;
  children?: NavigationItem[];
  /** When true, only shown to admins (is_superuser). */
  adminOnly?: boolean;
}

interface NavigationGroup {
  label?: string;
  items: NavigationItem[];
}

const navigationGroups: NavigationGroup[] = [
  {
    // Primary navigation (always visible, no label)
    items: [
      { text: 'Dashboard', icon: <DashboardIcon />, path: '/' },
      { text: 'Projects', icon: <FolderIcon />, path: '/projects' },
      { text: 'Tasks', icon: <AssignmentIcon />, path: '/tasks' },
      { text: 'Analytics', icon: <AnalyticsIcon />, path: '/analytics' },
      { text: 'Sprint Capacity', icon: <SprintCapacityIcon />, path: '/sprint-capacity' },
    ],
  },
  {
    label: 'Data Management',
    items: [
      { text: 'Knowledge', icon: <KnowledgeIcon />, path: '/knowledge' },
      {
        text: 'Traceability',
        icon: <TraceabilityIcon />,
        path: '/traceability',
        children: [
          { text: 'D3 Visualization', icon: <VisualizationIcon />, path: '/traceability/visualization' },
          { text: 'Rule Builder', icon: <RuleBuilderIcon />, path: '/traceability/flow-builder' },
          { text: 'Rules', icon: <AssignmentIcon />, path: '/traceability/rules' },
          { text: 'Review Queue', icon: <QualityIcon />, path: '/traceability/review' },
          { text: 'Execution History', icon: <HistoryIcon />, path: '/traceability/history' },
          {
            text: 'Sync Health (All Projects)',
            icon: <SyncHealthIcon />,
            path: '/traceability/sync-health',
            adminOnly: true,
          },
        ],
      },
      { text: 'Quality', icon: <QualityIcon />, path: '/quality' },
    ],
  },
  {
    label: 'Testing',
    items: [
      { text: 'Test Results', icon: <TestingIcon />, path: '/testing' },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { text: 'Jira Fields', icon: <JiraFieldsIcon />, path: '/jira-fields' },
      { text: 'Settings', icon: <SettingsIcon />, path: '/settings' },
    ],
  },
];

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const location = useLocation();
  const user = useSelector((s: RootState) => s.auth.user);
  const isAdmin = Boolean(user?.is_superuser);
  // Hide admin-only entries (e.g. cross-project Sync Health) from non-admins.
  const visibleGroups = useMemo(
    () =>
      navigationGroups
        .map((group) => ({
          ...group,
          items: group.items
            .filter((item) => isAdmin || !item.adminOnly)
            .map((item) =>
              item.children
                ? { ...item, children: item.children.filter((child) => isAdmin || !child.adminOnly) }
                : item,
            ),
        }))
        .filter((group) => group.items.length > 0),
    [isAdmin],
  );
  const pageTitle = resolveRouteTitle(location.pathname);
  const showProjectSelector =
    location.pathname === '/' ||
    PROJECT_SELECTOR_ROUTES.some((p) => location.pathname.startsWith(p));
  const userName = user?.full_name || user?.username || user?.email || 'Account';

  // Load collapsed state from localStorage
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>(() => {
    return readStoredJson<Record<string, boolean>>('navigation_collapsed_groups', {});
  });

  // Track which items with children are expanded
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});

  const toggleGroup = (label: string) => {
    const newState = {
      ...collapsedGroups,
      [label]: !collapsedGroups[label],
    };
    setCollapsedGroups(newState);
    writeStoredJson('navigation_collapsed_groups', newState);
  };

  const toggleItem = (itemText: string) => {
    setExpandedItems({
      ...expandedItems,
      [itemText]: !expandedItems[itemText],
    });
  };

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleMenuClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const handleLogout = () => {
    handleMenuClose();
    void performLogout(dispatch, navigate);
  };

  const drawer = (
    <div>
      <Toolbar>
        <Typography variant="h6" noWrap component="div">
          PO Helper
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        {visibleGroups.map((group, groupIndex) => (
          <React.Fragment key={groupIndex}>
            {/* Primary navigation (no label, always visible) */}
            {!group.label && (
              <>
                {group.items.map((item) => (
                  <ListItem key={item.text} disablePadding>
                    <ListItemButton onClick={() => navigate(item.path)}>
                      <ListItemIcon>{item.icon}</ListItemIcon>
                      <ListItemText primary={item.text} />
                    </ListItemButton>
                  </ListItem>
                ))}
                <Divider sx={{ my: 1 }} />
              </>
            )}

            {/* Secondary navigation (with collapsible groups) */}
            {group.label && (
              <>
                <ListItem disablePadding>
                  <ListItemButton onClick={() => toggleGroup(group.label!)}>
                    <ListItemText
                      primary={group.label}
                      primaryTypographyProps={{
                        variant: 'caption',
                        color: 'text.secondary',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        letterSpacing: 1.1,
                      }}
                    />
                    {collapsedGroups[group.label] ? <ExpandMore /> : <ExpandLess />}
                  </ListItemButton>
                </ListItem>
                <Collapse in={!collapsedGroups[group.label]} timeout="auto" unmountOnExit>
                  <List component="div" disablePadding>
                    {group.items.map((item) => (
                      <React.Fragment key={item.text}>
                        <ListItem disablePadding>
                          <ListItemButton
                            onClick={() => {
                              // A parent entry is a real destination: clicking
                              // it must navigate, not merely toggle the
                              // submenu. Collapse stays available on the
                              // chevron (stopPropagation below).
                              navigate(item.path);
                              if (item.children) {
                                setExpandedItems((prev) => ({ ...prev, [item.text]: true }));
                              }
                            }}
                            sx={{ pl: 4 }}
                          >
                            <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                            <ListItemText primary="item.text" />
                            {item.children && (
                              <Box
                                component="span"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleItem(item.text);
                                }}
                                sx={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}
                                aria-label={expandedItems[item.text] ? 'Collapse submenu' : 'Expand submenu'}
                              >
                                {expandedItems[item.text] ? <ExpandLess /> : <ExpandMore />}
                              </Box>
                            )}
                          </ListItemButton>
                        </ListItem>
                        {item.children && (
                          <Collapse in={expandedItems[item.text]} timeout="auto" unmountOnExit>
                            <List component="div" disablePadding>
                              {item.children.map((child) => (
                                <ListItem key={child.text} disablePadding>
                                  <ListItemButton onClick={() => navigate(child.path)} sx={{ pl: 8 }}>
                                    <ListItemIcon sx={{ minWidth: 40 }}>{child.icon}</ListItemIcon>
                                    <ListItemText primary={child.text} />
                                  </ListItemButton>
                                </ListItem>
                              ))}
                            </List>
                          </Collapse>
                        )}
                      </React.Fragment>
                    ))}
                  </List>
                </Collapse>
              </>
            )}
          </React.Fragment>
        ))}
      </List>
    </div>
  );

  return (
    <Box sx={{ display: 'flex', width: '100%' }}>
      <AppBar
        position="fixed"
        color="default"
        elevation={0}
        sx={{
          width: { sm: `calc(100% - ${drawerWidth}px)` },
          ml: { sm: `${drawerWidth}px` },
        }}
      >
        <Toolbar sx={{ gap: 1 }}>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 1, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap component="h1" sx={{ flexGrow: 1, fontWeight: 600 }}>
            {pageTitle}
          </Typography>
          {showProjectSelector && <ProjectSelector compact />}
          <IconButton onClick={handleMenuClick} sx={{ ml: 1, borderRadius: 2 }} aria-label="account menu">
            <Stack direction="row" spacing={1} alignItems="center">
              <Avatar sx={{ bgcolor: 'secondary.main', width: 32, height: 32 }}>
                <PersonIcon fontSize="small" />
              </Avatar>
              <Typography
                variant="body2"
                sx={{ display: { xs: 'none', md: 'block' }, maxWidth: 160, color: 'text.primary' }}
                noWrap
              >
                {userName}
              </Typography>
            </Stack>
          </IconButton>
          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={handleMenuClose}
          >
            <MenuItem disabled sx={{ opacity: '1 !important', display: 'block', py: 1 }}>
              <Typography variant="subtitle2" noWrap>{userName}</Typography>
              {user?.email && (
                <Typography variant="caption" color="text.secondary" noWrap component="div">
                  {user.email}
                </Typography>
              )}
            </MenuItem>
            <Divider />
            <MenuItem onClick={() => { handleMenuClose(); navigate('/profile'); }}>
              <PersonIcon sx={{ mr: 1 }} fontSize="small" /> Profile
            </MenuItem>
            <MenuItem onClick={handleLogout}>
              <LogoutIcon sx={{ mr: 1 }} fontSize="small" /> Logout
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Box
        component="nav"
        sx={{ width: { sm: drawerWidth }, flexShrink: { sm: 0 } }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{
            keepMounted: true,
          }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
          }}
        >
          {drawer}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { sm: `calc(100% - ${drawerWidth}px)` },
        }}
      >
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  );
}


