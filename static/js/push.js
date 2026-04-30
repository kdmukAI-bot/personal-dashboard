window.PD = window.PD || {};

PD.Push = (() => {
  let swReg = null;

  function urlBase64ToUint8Array(base64) {
    const padding = '='.repeat((4 - base64.length % 4) % 4);
    const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(b64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function init() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      return { permission: 'unsupported', subscribed: false };
    }
    swReg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    await navigator.serviceWorker.ready;
    const sub = await swReg.pushManager.getSubscription();
    return { permission: Notification.permission, subscribed: !!sub };
  }

  async function subscribe() {
    if (!swReg) await init();
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') throw new Error('Notification permission denied: ' + perm);
    const res = await fetch('/api/push/vapid-public-key');
    if (!res.ok) throw new Error('Failed to fetch VAPID key: ' + res.status);
    const { public_key: key } = await res.json();
    if (!key) throw new Error('VAPID key missing in response');
    const sub = await swReg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
    const json = sub.toJSON();
    const post = await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint: json.endpoint,
        keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
        user_agent: navigator.userAgent,
      }),
    });
    if (!post.ok) throw new Error('Failed to register subscription: ' + post.status);
    return sub;
  }

  async function unsubscribe() {
    if (!swReg) await init();
    const sub = await swReg.pushManager.getSubscription();
    if (!sub) return false;
    const post = await fetch('/api/push/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    });
    if (!post.ok) throw new Error('Failed to unregister: ' + post.status);
    return await sub.unsubscribe();
  }

  async function testSend() {
    const res = await fetch('/api/push/test', { method: 'POST' });
    if (!res.ok) throw new Error('Test send failed: ' + res.status);
    return res;
  }

  async function refreshUI() {
    const status = document.getElementById('pd-push-status');
    const btnEnable = document.getElementById('pd-push-enable');
    const btnDisable = document.getElementById('pd-push-disable');
    const btnTest = document.getElementById('pd-push-test');
    const state = await init();
    if (status) {
      status.textContent = state.permission === 'unsupported'
        ? 'Push not supported in this browser'
        : `Permission: ${state.permission}; Subscribed: ${state.subscribed ? 'yes' : 'no'}`;
    }
    const sub = state.subscribed;
    const supported = state.permission !== 'unsupported';
    if (btnEnable) btnEnable.hidden = !supported || sub;
    if (btnDisable) btnDisable.hidden = !sub;
    if (btnTest) btnTest.hidden = !sub;
  }

  function wire() {
    const btnEnable = document.getElementById('pd-push-enable');
    const btnDisable = document.getElementById('pd-push-disable');
    const btnTest = document.getElementById('pd-push-test');
    if (btnEnable) btnEnable.addEventListener('click', async () => {
      try { await subscribe(); await refreshUI(); }
      catch (e) { alert('Subscribe failed: ' + e.message); }
    });
    if (btnDisable) btnDisable.addEventListener('click', async () => {
      try { await unsubscribe(); await refreshUI(); }
      catch (e) { alert('Unsubscribe failed: ' + e.message); }
    });
    if (btnTest) btnTest.addEventListener('click', async () => {
      try { await testSend(); }
      catch (e) { alert('Test send failed: ' + e.message); }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    wire();
    refreshUI().catch((e) => console.warn('[PD.Push] init failed', e));
  });

  return { init, subscribe, unsubscribe, testSend };
})();
