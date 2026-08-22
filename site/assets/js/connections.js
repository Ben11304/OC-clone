// Copyright (c) 2024-2026 OpenConstruction Open Science Initiative
// SPDX-License-Identifier: Apache-2.0

(() => {
  const marks = {
    github: 'GH',
    huggingface: 'HF',
    baidu: '度'
  };
  const serverSettings = {
    github: 'OC_GITHUB_CLIENT_ID and OC_GITHUB_CLIENT_SECRET',
    huggingface: 'OC_HF_CLIENT_ID and OC_HF_CLIENT_SECRET',
    baidu: 'OC_BAIDU_CLIENT_ID and OC_BAIDU_CLIENT_SECRET'
  };

  function esc(value){
    return window.OCAuth?.escapeHtml
      ? window.OCAuth.escapeHtml(value)
      : String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }

  function apiUrl(path){
    return `${String(window.OC_AGENT_API_URL || '').replace(/\/$/, '')}${path}`;
  }

  async function sessionToken(){
    const client = window.OCAuth?.getClient?.();
    if (!client) throw new Error('OpenConstruction authentication is unavailable.');
    const { data, error } = await client.auth.getSession();
    if (error) throw error;
    if (!data?.session?.access_token) throw new Error('Sign in to manage connected accounts.');
    return data.session.access_token;
  }

  async function api(path, options = {}){
    const token = await sessionToken();
    const response = await fetch(apiUrl(path), {
      ...options,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        ...(options.headers || {})
      }
    });
    const payload = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.error_description || payload.error || `Request failed (${response.status})`);
    return payload;
  }

  function formatDate(timestamp){
    if (!timestamp) return '';
    const date = new Date(Number(timestamp) * 1000);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function providerCard(provider){
    const account = provider.display_name || provider.account_id || 'Connected account';
    const scopeText = (provider.scopes || []).join(', ');
    return `
      <article class="oc-connection-card" data-connection-provider="${esc(provider.id)}">
        <div class="oc-connection-card-head">
          <div class="oc-connection-provider">
            <span class="oc-connection-provider-mark" aria-hidden="true">${esc(marks[provider.id] || provider.name.slice(0, 2))}</span>
            <h4>${esc(provider.name)}</h4>
          </div>
          <span class="oc-connection-state${provider.connected ? ' is-connected' : ''}">${provider.connected ? 'Connected' : 'Not connected'}</span>
        </div>
        <p>${esc(provider.description)}</p>
        ${provider.connected ? `
          <div class="oc-connection-account">
            <strong>${esc(account)}</strong>
            ${scopeText ? `<span>Permissions: ${esc(scopeText)}</span>` : ''}
            ${provider.updated_at ? `<span>Updated ${esc(formatDate(provider.updated_at))}</span>` : ''}
          </div>
        ` : ''}
        <div class="oc-connection-card-actions">
          ${provider.connected
            ? `<button type="button" class="oc-text-action" data-disconnect-provider="${esc(provider.id)}">Disconnect</button>`
            : `<button type="button" class="oc-text-action" data-connect-provider="${esc(provider.id)}" data-provider-configured="${provider.configured ? 'true' : 'false'}"${provider.configured ? '' : ' aria-disabled="true"'}>${provider.configured ? `Connect ${esc(provider.name)}` : 'OAuth setup required'}</button>`}
          ${provider.documentation_url ? `<a class="oc-text-action" href="${esc(provider.documentation_url)}" target="_blank" rel="noopener">Provider docs</a>` : ''}
        </div>
      </article>
    `;
  }

  function callbackNotice(){
    const params = new URLSearchParams(window.location.search);
    const state = params.get('connection');
    if (!state) return '';
    const provider = params.get('provider') || 'provider';
    const message = params.get('message') || '';
    if (state === 'success') return `<div class="oc-connections-notice">${esc(provider)} connected successfully. The credential is stored server-side.</div>`;
    return `<div class="oc-connections-notice is-error">Could not connect ${esc(provider)}${message ? `: ${esc(message)}` : '.'}</div>`;
  }

  function showSetupNotice(root, provider){
    const callback = new URL(apiUrl(`/api/connections/${encodeURIComponent(provider.id)}/callback`), window.location.href).href;
    const notice = document.createElement('div');
    notice.className = 'oc-connections-notice is-error oc-connections-runtime-notice';
    notice.setAttribute('role', 'status');
    notice.innerHTML = `OAuth for <strong>${esc(provider.name)}</strong> is not configured on this OC server yet. Register an OAuth app with callback <code>${esc(callback)}</code>, then set <code>${esc(serverSettings[provider.id] || 'the provider client credentials')}</code> on the server.`;
    root.querySelector('.oc-connections-runtime-notice')?.remove();
    root.prepend(notice);
    notice.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  async function mount(root = document.querySelector('[data-oc-connections-root]')){
    if (!root) return;
    let providerRows = [];
    root.innerHTML = `${callbackNotice()}<div class="oc-connection-grid"><div class="skeleton" style="min-height:220px"></div></div>`;
    try {
      const payload = await api('/api/connections');
      providerRows = payload.providers || [];
      root.innerHTML = `${callbackNotice()}<div class="oc-connection-grid">${providerRows.map(providerCard).join('')}</div><p class="small text-muted mt-3 mb-0">Public datasets remain downloadable without a connected account. OC uses a provider credential only when that source requires your identity, approval, or quota.</p>`;
      root.querySelectorAll('[data-connect-provider]').forEach(button => {
        button.dataset.providerName = providerRows.find(provider => provider.id === button.dataset.connectProvider)?.name || button.dataset.connectProvider;
      });
    } catch (error) {
      root.innerHTML = `${callbackNotice()}<div class="oc-connections-notice is-error">Connected Accounts API is unavailable: ${esc(error.message || error)}</div>`;
      return;
    }

    root.querySelectorAll('[data-connect-provider]').forEach(button => {
      button.addEventListener('click', async () => {
        if (button.dataset.providerConfigured !== 'true') {
          const provider = providerRows.find(item => item.id === button.dataset.connectProvider) || {
            id: button.dataset.connectProvider,
            name: button.dataset.providerName || button.dataset.connectProvider
          };
          showSetupNotice(root, provider);
          return;
        }
        const original = button.textContent;
        button.disabled = true;
        button.textContent = 'Opening provider...';
        try {
          const payload = await api(`/api/connections/${encodeURIComponent(button.dataset.connectProvider)}/start`, { method: 'POST' });
          if (!payload.authorization_url) throw new Error('Provider returned no authorization URL.');
          window.location.assign(payload.authorization_url);
        } catch (error) {
          button.textContent = error.message || 'Connection failed';
          window.setTimeout(() => { button.textContent = original; button.disabled = false; }, 2200);
        }
      });
    });

    root.querySelectorAll('[data-disconnect-provider]').forEach(button => {
      button.addEventListener('click', async () => {
        const provider = button.dataset.disconnectProvider;
        if (!window.confirm(`Disconnect ${provider} from OpenConstruction?`)) return;
        button.disabled = true;
        button.textContent = 'Disconnecting...';
        try {
          await api(`/api/connections/${encodeURIComponent(provider)}`, { method: 'DELETE' });
          await mount(root);
        } catch (error) {
          button.textContent = error.message || 'Disconnect failed';
          window.setTimeout(() => { button.textContent = 'Disconnect'; button.disabled = false; }, 2200);
        }
      });
    });
  }

  window.OCConnections = { mount, list: () => api('/api/connections') };
})();
