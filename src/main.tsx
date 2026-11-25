import { createRoot } from 'react-dom/client';
import '@fontsource-variable/geist';
import '@fontsource-variable/noto-sans-sc';
import { App } from './App';
import './index.css';

createRoot(document.getElementById('root')!).render(<App />);
