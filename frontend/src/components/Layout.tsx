import React, { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
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
  ExpandLess,
  ExpandMore,
} from '@mui/icons-material';
import { Collapse } from '@mui/material';
import { useDispatch } from 'react-redux';
import { performLogout } from '../utils/logout';

const drawerWidth = 240;

interface NavigationItem {
  text: string;
  icon: React.ReactNode;
  path: string;
  children?: NavigationItem[];
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
          { text: 'Rule Builder', icon: <RuleBuilderIcon />, path: '/traceability/flow-builder' },
          { text: 'Execution History', icon: <HistoryIcon />, path: '/traceability/history' },
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

  // Load collapsed state from localStorage
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>(() => {
    const saved = localStorage.getItem('navigation_collapsed_groups');
    return saved ? JSON.parse(saved) : {};
  });

  // Track which items with children are expanded
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});

  const toggleGroup = (label: string) => {
    const newState = {
      ...collapsedGroups,
      [label]: !collapsedGroups[label],
    };
    setCollapsedGroups(newState);
    localStorage.setItem('navigation_collapsed_groups', JSON.stringify(newState));
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
    performLogout(dispatch, navigate);
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
        {navigationGroups.map((group, groupIndex) => (
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
                              if (item.children) {
                                toggleItem(item.text);
                              } else {
                                navigate(item.path);
                              }
                            }}
                            sx={{ pl: 4 }}
                          >
                            <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                            <ListItemText primary={item.text} />
                            {item.children && (expandedItems[item.text] ? <ExpandLess /> : <ExpandMore />)}
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
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
            Product Owner Helper
          </Typography>
          <IconButton onClick={handleMenuClick} sx={{ p: 0 }}>
            <Avatar sx={{ bgcolor: 'secondary.main' }}>
              <PersonIcon />
            </Avatar>
          </IconButton>
          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={handleMenuClose}
          >
            <MenuItem onClick={() => { handleMenuClose(); navigate('/profile'); }}>Profile</MenuItem>
            <MenuItem onClick={handleLogout}>
              <LogoutIcon sx={{ mr: 1 }} /> Logout
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


