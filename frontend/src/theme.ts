import { alpha, createTheme } from '@mui/material/styles';
import '@mui/x-data-grid/themeAugmentation';

const primary = '#0B4F6C'; // deep banking blue
const secondary = '#0093A4'; // modern teal
const bgDefault = '#F4F6F8';
const bgPaper = '#FFFFFF';
const textPrimary = '#1A1F36';
const textSecondary = '#3C4758';
const border = '#E6EBF2';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: primary },
    secondary: { main: secondary },
    success: { main: '#2E7D32' },
    warning: { main: '#ED6C02' },
    error: { main: '#C62828' },
    info: { main: '#1565C0' },
    background: { default: bgDefault, paper: bgPaper },
    text: { primary: textPrimary, secondary: textSecondary },
    divider: border,
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily:
      'Inter, Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
    h1: { fontWeight: 700, letterSpacing: -0.5 },
    h2: { fontWeight: 700, letterSpacing: -0.2 },
    h3: { fontWeight: 700 },
    h4: { fontWeight: 700 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: bgDefault,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: bgPaper,
          color: textPrimary,
          borderBottom: `1px solid ${border}`,
        },
      },
    },
    MuiToolbar: {
      styleOverrides: {
        root: { minHeight: 64 },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#F8FAFC',
          borderRight: `1px solid ${border}`,
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 8 },
        containedPrimary: { boxShadow: 'none' },
        sizeLarge: { padding: '10px 18px' },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          border: `1px solid ${border}`,
          boxShadow: '0 6px 12px rgba(16,24,40,0.04)',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          '&.Mui-selected': {
            backgroundColor: `${alpha(primary, 0.08)} !important`,
            color: primary,
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 6, fontWeight: 500 },
      },
    },
    MuiPaper: {
      styleOverrides: { root: { backgroundImage: 'none' } },
    },
    // DataGrid (MUI X)
    MuiDataGrid: {
      styleOverrides: {
        root: { border: 'none' },
        columnHeaders: {
          backgroundColor: '#F0F4F8',
          borderBottom: `1px solid ${border}`,
        },
        cell: {
          borderColor: '#F0F2F5',
        },
      },
    },
  },
});

export default theme;
