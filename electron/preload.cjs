const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('publisher', {
  request: (method, args = {}) => ipcRenderer.invoke('publisher:request', method, args),
  selectMedia: kind => ipcRenderer.invoke('publisher:select-media', kind),
  filePath: file => {
    const path = webUtils.getPathForFile(file);
    if (path) ipcRenderer.send('publisher:register-preview', path);
    return path;
  },
  mediaPreview: path => ipcRenderer.invoke('publisher:media-preview', path),
  update: action => ipcRenderer.invoke('publisher:update', action),
  subscribeUpdates: callback => {
    const listener = (_, status) => callback(status);
    ipcRenderer.on('publisher:update-changed', listener);
    return () => ipcRenderer.removeListener('publisher:update-changed', listener);
  },
  subscribe: callback => {
    const listener = () => callback();
    ipcRenderer.on('publisher:changed', listener);
    return () => ipcRenderer.removeListener('publisher:changed', listener);
  },
});
