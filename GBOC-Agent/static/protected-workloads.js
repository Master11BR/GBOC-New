// GBOC System v14.5.0 Enterprise Edition
// Module: Protected Workloads Controller (Database, AD, Tape, Enterprise)

function switchWorkloadTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.remove('btn-primary', 'active');
        b.classList.add('btn-secondary');
    });
    document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');

    const activeBtn = document.getElementById('tab-btn-' + tabId);
    const activePane = document.getElementById('pane-' + tabId);

    if (activeBtn) {
        activeBtn.classList.remove('btn-secondary');
        activeBtn.classList.add('btn-primary', 'active');
    }
    if (activePane) {
        activePane.style.display = 'block';
    }

    // Persistir estado na URL
    const url = new URL(window.location);
    url.searchParams.set('tab', tabId);
    window.history.replaceState({}, '', url);
}

document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    const requestedTab = params.get('tab');
    if (requestedTab && document.getElementById('pane-' + requestedTab)) {
        switchWorkloadTab(requestedTab);
    }
});
