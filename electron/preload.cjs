const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('publisher', {
  request: (method, args = {}) => ipcRenderer.invoke('publisher:request', method, args),
  selectMedia: kind => ipcRenderer.invoke('publisher:select-media', kind),
  materialAction: (action, args = {}) => ipcRenderer.invoke('publisher:material-action', action, args),
  voiceAction: (action, args = {}) => ipcRenderer.invoke('publisher:voice-action', action, args),
  subscribeVoice: callback => {
    const listener = () => callback();
    ipcRenderer.on('publisher:voice-changed', listener);
    return () => ipcRenderer.removeListener('publisher:voice-changed', listener);
  },
  subscribeMaterials: callback => {
    const listener = () => callback();
    ipcRenderer.on('publisher:materials-changed', listener);
    return () => ipcRenderer.removeListener('publisher:materials-changed', listener);
  },
  selectCommentCache: () => ipcRenderer.invoke('publisher:select-comment-cache'),
  takeCommentDestination: () => ipcRenderer.invoke('publisher:comment-destination'),
  openCommentSource: destination => ipcRenderer.invoke('publisher:open-comment-source', destination),
  openDouyinMessages: kind => ipcRenderer.invoke('publisher:open-douyin-messages', kind),
  douyinPane: (action, args) => ipcRenderer.invoke('publisher:douyin-pane', action, args),
  subscribeDouyinPane: callback => {
    const listener = (_, token, status) => callback(token, status);
    ipcRenderer.on('publisher:douyin-pane-status', listener);
    return () => ipcRenderer.removeListener('publisher:douyin-pane-status', listener);
  },
  subscribeCommentDestination: callback => {
    const listener = () => callback();
    ipcRenderer.on('publisher:comment-destination', listener);
    return () => ipcRenderer.removeListener('publisher:comment-destination', listener);
  },
  subscribeComments: callback => {
    const listener = (_, groupId) => callback(groupId);
    ipcRenderer.on('publisher:comments-changed', listener);
    return () => ipcRenderer.removeListener('publisher:comments-changed', listener);
  },
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
