import React, { useEffect, useState } from 'react';
import {
  Box,
  Typography,
  Card,
  TextField,
  Button,
  Grid,
  Tabs,
  Tab,
  Avatar,
  Snackbar,
  Alert,
  Divider,
} from '@mui/material';
import { Save as SaveIcon, Password as PasswordIcon } from '@mui/icons-material';
import { useDispatch, useSelector } from 'react-redux';
import type { RootState, AppDispatch } from '../store/store';
import { setUser } from '../store/authSlice';
import { getCurrentUser, updateCurrentUser, changePassword } from '../services/api';
import MFASettings from '../components/security/MFASettings';

function TabPanel(props: { children?: React.ReactNode; index: number; value: number }) {
  const { children, value, index, ...other } = props;
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

const initials = (name?: string, email?: string) => {
  const src = name && name.trim().length > 0 ? name : email || 'U';
  return src
    .split(/\s|@/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join('');
};

const Profile: React.FC = () => {
  const dispatch = useDispatch<AppDispatch>();
  const user = useSelector((s: RootState) => s.auth.user);
  const [tab, setTab] = useState(0);
  const [form, setForm] = useState({ full_name: '', username: '', email: '' });
  const [pwd, setPwd] = useState({ current: '', next: '', confirm: '' });
  const [toast, setToast] = useState<{ open: boolean; type: 'success' | 'error'; msg: string }>({ open: false, type: 'success', msg: '' });
  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTab(newValue);
  };

  useEffect(() => {
    (async () => {
      try {
        const me = await getCurrentUser();
        dispatch(setUser(me));
        setForm({ full_name: me.full_name || '', username: me.username, email: me.email });
      } catch {
        setToast({ open: true, type: 'error', msg: 'Failed to load profile' });
      }
    })();
  }, [dispatch]);

  const saveProfile = async () => {
    try {
      const updated = await updateCurrentUser({ full_name: form.full_name, username: form.username });
      dispatch(setUser(updated));
      setToast({ open: true, type: 'success', msg: 'Profile updated' });
    } catch {
      setToast({ open: true, type: 'error', msg: 'Failed to update profile' });
    }
  };

  const savePassword = async () => {
    if (pwd.next !== pwd.confirm) {
      setToast({ open: true, type: 'error', msg: 'Passwords do not match' });
      return;
    }
    try {
      await changePassword({ current_password: pwd.current, new_password: pwd.next });
      setToast({ open: true, type: 'success', msg: 'Password updated' });
      setPwd({ current: '', next: '', confirm: '' });
    } catch {
      setToast({ open: true, type: 'error', msg: 'Failed to update password' });
    }
  };

  return (
    <Box>
      <Box display="flex" alignItems="center" gap={2} mb={2}>
        <Avatar sx={{ bgcolor: 'primary.main', width: 56, height: 56 }}>
          {initials(user?.full_name, user?.email)}
        </Avatar>
        <Box>
          <Typography variant="h4">Profile</Typography>
          <Typography color="text.secondary">Manage your personal settings</Typography>
        </Box>
      </Box>

      <Card>
        <Tabs value={tab} onChange={handleTabChange}>
          <Tab label="Profile" />
          <Tab label="Security" />
          <Tab label="Preferences" />
        </Tabs>

        <TabPanel value={tab} index={0}>
          <Grid container spacing={3}>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Full Name"
                fullWidth
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Username"
                fullWidth
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Email" fullWidth value={form.email} InputProps={{ readOnly: true }} />
            </Grid>
            <Grid item xs={12}>
              <Button variant="contained" startIcon={<SaveIcon />} onClick={saveProfile}>
                Save
              </Button>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tab} index={1}>
          {/* Two-Factor Authentication Section */}
          <MFASettings />

          <Divider sx={{ my: 4 }} />

          {/* Password Change Section */}
          <Typography variant="h6" gutterBottom>
            Change Password
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Update your password regularly to keep your account secure
          </Typography>
          <Grid container spacing={3}>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Current Password"
                type="password"
                fullWidth
                value={pwd.current}
                onChange={(e) => setPwd({ ...pwd, current: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                label="New Password"
                type="password"
                fullWidth
                value={pwd.next}
                onChange={(e) => setPwd({ ...pwd, next: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Confirm New Password"
                type="password"
                fullWidth
                value={pwd.confirm}
                onChange={(e) => setPwd({ ...pwd, confirm: e.target.value })}
              />
            </Grid>
            <Grid item xs={12}>
              <Button variant="contained" startIcon={<PasswordIcon />} onClick={savePassword}>
                Change Password
              </Button>
            </Grid>
          </Grid>
        </TabPanel>

        <TabPanel value={tab} index={2}>
          <Typography color="text.secondary">Coming soon: theme and notifications</Typography>
        </TabPanel>
      </Card>

      <Snackbar open={toast.open} autoHideDuration={3000} onClose={() => setToast({ ...toast, open: false })}>
        <Alert severity={toast.type} sx={{ width: '100%' }}>
          {toast.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default Profile;
