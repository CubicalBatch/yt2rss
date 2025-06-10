let currentChannelName = null;
let isEditMode = false;
let refreshInterval = null;

// Copy feed URL functionality
async function copyFeedUrl(url, button) {
    try {
        await navigator.clipboard.writeText(url);
        
        // Update button
        const originalText = button.innerHTML;
        button.innerHTML = '✅ Copied!';
        button.classList.add('copied');
        
        // Show toast
        showToast('📋 Feed URL copied to clipboard!');
        
        // Reset after 2 seconds
        setTimeout(() => {
            button.innerHTML = originalText;
            button.classList.remove('copied');
        }, 2000);
        
    } catch (err) {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = url;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        
        // Show feedback
        button.innerHTML = '✅ Copied!';
        button.classList.add('copied');
        
        setTimeout(() => {
            button.innerHTML = '📋 Copy RSS Feed URL';
            button.classList.remove('copied');
        }, 2000);
    }
}

// Toast notification
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    
    // Remove existing type classes
    toast.classList.remove('success', 'error', 'warning');
    
    // Auto-detect message type based on emoji/content
    if (message.includes('✅') || message.toLowerCase().includes('success')) {
        toast.classList.add('success');
    } else if (message.includes('❌') || message.toLowerCase().includes('error') || message.toLowerCase().includes('failed')) {
        toast.classList.add('error');
    } else if (message.includes('⚠️') || message.toLowerCase().includes('warning')) {
        toast.classList.add('warning');
    }
    // Default style (neutral) if no specific type detected
    
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Modal management
function openAddChannelModal() {
    isEditMode = false;
    currentChannelName = null;
    document.getElementById('modalTitle').textContent = 'Add New Channel';
    document.getElementById('submitBtn').textContent = 'Add Channel';
    document.getElementById('dangerZone').style.display = 'none';
    clearForm();
    
    // Pre-check sponsor-related categories
    document.getElementById('sponsor').checked = true;
    document.getElementById('selfpromo').checked = true;
    document.getElementById('interaction').checked = true;
    
    document.getElementById('channelModal').style.display = 'block';
    setTimeout(adjustTooltipPositions, 100);
}

async function openEditChannelModal(channelName) {
    isEditMode = true;
    currentChannelName = channelName;
    document.getElementById('modalTitle').textContent = 'Edit Channel';
    document.getElementById('submitBtn').textContent = 'Update Channel';
    document.getElementById('dangerZone').style.display = 'block';
    
    // Reset danger zone to collapsed state
    document.getElementById('dangerZoneContent').classList.remove('expanded');
    document.getElementById('dangerZoneToggle').classList.remove('rotated');
    
    // Load channel data
    try {
        const response = await fetch('/api/channels');
        const data = await response.json();
        const channel = data.channels.find(ch => ch.name === channelName);
        
        if (channel) {
            populateForm(channel);
            document.getElementById('channelModal').style.display = 'block';
            setTimeout(adjustTooltipPositions, 100);
        } else {
            showToast('❌ Channel not found');
        }
    } catch (error) {
        console.error('Error loading channel data:', error);
        showToast('❌ Error loading channel data');
    }
}

function closeChannelModal() {
    document.getElementById('channelModal').style.display = 'none';
    clearForm();
}

function toggleDangerZone() {
    const content = document.getElementById('dangerZoneContent');
    const toggle = document.getElementById('dangerZoneToggle');
    
    if (content.classList.contains('expanded')) {
        content.classList.remove('expanded');
        toggle.classList.remove('rotated');
    } else {
        content.classList.add('expanded');
        toggle.classList.add('rotated');
    }
}

// Scheduler modal management
async function openScheduleModal() {
    try {
        const response = await fetch('/api/config/refresh-interval');
        const data = await response.json();
        
        if (response.ok) {
            document.getElementById('refreshInterval').value = data.refresh_interval_hours;
            document.getElementById('currentInterval').textContent = `${data.refresh_interval_hours} hours`;
            
            const nextRun = data.next_run ? formatDateTime(data.next_run) : 'Not scheduled';
            document.getElementById('nextRun').textContent = nextRun;
            
            document.getElementById('scheduleModal').style.display = 'block';
        } else {
            showToast('❌ Failed to load scheduler settings');
        }
    } catch (error) {
        console.error('Error loading scheduler settings:', error);
        showToast('❌ Network error occurred');
    }
}

function closeScheduleModal() {
    document.getElementById('scheduleModal').style.display = 'none';
}

// Form management
function clearForm() {
    document.getElementById('channelForm').reset();
    // Clear all checkboxes
    const checkboxes = document.querySelectorAll('#channelForm input[type="checkbox"]');
    checkboxes.forEach(cb => cb.checked = false);
}

function populateForm(channel) {
    document.getElementById('channelDisplayName').value = channel.display_name || channel.name || '';
    document.getElementById('channelUrl').value = channel.url || '';
    document.getElementById('maxVideos').value = channel.max_episodes || '';
    document.getElementById('downloadDelay').value = channel.download_delay_hours || '';
    document.getElementById('format').value = channel.format || 'video';
    document.getElementById('quality').value = channel.quality || 'max';
    
    // Set SponsorBlock categories
    const categories = channel.sponsorblock_categories || [];
    const checkboxes = document.querySelectorAll('#channelForm input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.checked = categories.includes(cb.value);
    });
}

function getFormData() {
    const formData = {
        display_name: document.getElementById('channelDisplayName').value.trim(),
        url: document.getElementById('channelUrl').value.trim(),
        max_episodes: parseInt(document.getElementById('maxVideos').value) || 10,
        download_delay_hours: parseInt(document.getElementById('downloadDelay').value) || 6,
        format: document.getElementById('format').value || 'video',
        quality: document.getElementById('quality').value || 'max',
        sponsorblock_categories: []
    };
    
    // Get selected SponsorBlock categories
    const checkboxes = document.querySelectorAll('#channelForm input[type="checkbox"]:checked');
    formData.sponsorblock_categories = Array.from(checkboxes).map(cb => cb.value);
    
    return formData;
}

// API calls
async function handleSubmit(event) {
    event.preventDefault();
    
    const formData = getFormData();
    
    // Validate required fields
    if (!formData.display_name || !formData.url) {
        showToast('❌ Please fill in all required fields');
        return;
    }
    
    try {
        let response;
        if (isEditMode) {
            response = await fetch(`/api/channels/${currentChannelName}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            });
        } else {
            response = await fetch('/api/channels', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            });
        }
        
        const result = await response.json();
        
        if (response.ok) {
            showToast(isEditMode ? '✅ Channel updated successfully!' : '✅ Channel added successfully!');
            closeChannelModal();
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            showToast(`❌ ${result.error || 'Unknown error occurred'}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('❌ Network error occurred');
    }
}

async function deleteChannel(channelName) {
    if (!confirm(`Are you sure you want to delete the channel "${channelName}"? This action cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${channelName}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast('✅ Channel deleted successfully!');
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            showToast(`❌ ${result.error || 'Failed to delete channel'}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('❌ Network error occurred');
    }
}

async function purgeEpisodes() {
    if (!currentChannelName) {
        showToast('❌ No channel selected');
        return;
    }
    
    if (!confirm(`Are you sure you want to purge all downloaded episodes for "${currentChannelName}"? This will delete all video files and the RSS feed will be regenerated on next refresh. This action cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${currentChannelName}/purge`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast('✅ Episodes purged successfully!');
            closeChannelModal();
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            showToast(`❌ ${result.error || 'Failed to purge episodes'}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('❌ Network error occurred');
    }
}

async function deleteChannelFromDangerZone() {
    if (!currentChannelName) {
        showToast('❌ No channel selected');
        return;
    }
    
    await deleteChannel(currentChannelName);
}

// Scheduler form submission
async function handleScheduleSubmit(event) {
    event.preventDefault();
    
    const refreshInterval = parseInt(document.getElementById('refreshInterval').value);
    
    if (!refreshInterval || refreshInterval < 1 || refreshInterval > 168) {
        showToast('❌ Refresh interval must be between 1 and 168 hours');
        return;
    }
    
    try {
        const response = await fetch('/api/config/refresh-interval', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ refresh_interval_hours: refreshInterval })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast('✅ Refresh interval updated successfully!');
            
            // Update the display
            document.getElementById('currentInterval').textContent = `${refreshInterval} hours`;
            const nextRun = result.next_run ? formatDateTime(result.next_run) : 'Not scheduled';
            document.getElementById('nextRun').textContent = nextRun;
            
            closeScheduleModal();
        } else {
            showToast(`❌ ${result.error || 'Failed to update refresh interval'}`);
        }
    } catch (error) {
        console.error('Error updating refresh interval:', error);
        showToast('❌ Network error occurred');
    }
}

// Date formatting utility
function formatDateTime(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleString();
    } catch (error) {
        return 'Invalid date';
    }
}

// Event listeners
document.getElementById('channelForm').addEventListener('submit', handleSubmit);
document.getElementById('scheduleForm').addEventListener('submit', handleScheduleSubmit);

// Close modal when clicking outside
window.onclick = function(event) {
    const channelModal = document.getElementById('channelModal');
    const scheduleModal = document.getElementById('scheduleModal');
    
    if (event.target === channelModal) {
        closeChannelModal();
    } else if (event.target === scheduleModal) {
        closeScheduleModal();
    }
}

// Close modal with Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeChannelModal();
        closeScheduleModal();
    }
});

// Refresh functionality
async function triggerRefresh() {
    try {
        const response = await fetch('/api/refresh', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast('✅ Refresh started successfully!');
            startRefreshMonitoring();
        } else {
            showToast(`❌ ${result.error || 'Failed to start refresh'}`);
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('❌ Network error occurred');
    }
}

async function checkRefreshStatus() {
    try {
        const response = await fetch('/api/refresh/status');
        const status = await response.json();
        
        updateRefreshButton(status);
        
        if (!status.running && refreshInterval) {
            clearInterval(refreshInterval);
            refreshInterval = null;
            showToast('✅ Refresh completed!');
            
            // Reload page after 2 seconds to show updated data
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        }
        
    } catch (error) {
        console.error('Error checking refresh status:', error);
    }
}

function updateRefreshButton(status) {
    const refreshBtn = document.getElementById('refreshBtn');
    
    if (status.running) {
        refreshBtn.disabled = true;
        refreshBtn.classList.add('refreshing');
        refreshBtn.innerHTML = `<span class="spinner"></span>Refresh in progress (${status.duration}s)`;
    } else {
        refreshBtn.disabled = false;
        refreshBtn.classList.remove('refreshing');
        refreshBtn.innerHTML = '🔄 Refresh Podcasts';
    }
}

function startRefreshMonitoring() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    
    refreshInterval = setInterval(checkRefreshStatus, 1000); // Check every second
    checkRefreshStatus(); // Check immediately
}

// Relative time formatting
function formatRelativeTime(isoTimestamp) {
    try {
        const date = new Date(isoTimestamp);
        const now = new Date();
        const diffMs = now - date;
        
        // Convert to different units
        const diffSeconds = Math.floor(diffMs / 1000);
        const diffMinutes = Math.floor(diffSeconds / 60);
        const diffHours = Math.floor(diffMinutes / 60);
        const diffDays = Math.floor(diffHours / 24);
        const diffWeeks = Math.floor(diffDays / 7);
        const diffMonths = Math.floor(diffDays / 30);
        const diffYears = Math.floor(diffDays / 365);
        
        // Return appropriate format
        if (diffSeconds < 60) {
            return 'just now';
        } else if (diffMinutes < 60) {
            return `${diffMinutes}m ago`;
        } else if (diffHours < 24) {
            return `${diffHours}h ago`;
        } else if (diffDays < 7) {
            return `${diffDays}d ago`;
        } else if (diffWeeks < 4) {
            return `${diffWeeks}w ago`;
        } else if (diffMonths < 12) {
            return `${diffMonths}mo ago`;
        } else {
            return `${diffYears}y ago`;
        }
    } catch (error) {
        console.error('Error formatting relative time:', error);
        return 'unknown';
    }
}

function updateRelativeTimes() {
    const refreshTags = document.querySelectorAll('.last-refresh-tag[data-timestamp]');
    refreshTags.forEach(tag => {
        const timestamp = tag.getAttribute('data-timestamp');
        if (timestamp) {
            tag.textContent = 'Refreshed: ' + formatRelativeTime(timestamp);
        }
    });
}

// Tooltip positioning logic
function adjustTooltipPositions() {
    const tooltips = document.querySelectorAll('.tooltip');
    const modal = document.querySelector('.modal-content');
    
    if (!modal) return;
    
    tooltips.forEach(tooltip => {
        const rect = tooltip.getBoundingClientRect();
        const modalRect = modal.getBoundingClientRect();
        
        // Reset classes
        tooltip.classList.remove('tooltip-left', 'tooltip-right');
        
        // Check if tooltip would overflow to the right
        const tooltipContent = tooltip.querySelector('.tooltip-content');
        if (tooltipContent) {
            const tooltipWidth = 260; // Default tooltip width
            const tooltipCenter = rect.left + (rect.width / 2);
            const tooltipLeft = tooltipCenter - (tooltipWidth / 2);
            const tooltipRight = tooltipCenter + (tooltipWidth / 2);
            
            // If tooltip would overflow right edge of modal
            if (tooltipRight > modalRect.right - 20) {
                tooltip.classList.add('tooltip-right');
            }
            // If tooltip would overflow left edge of modal
            else if (tooltipLeft < modalRect.left + 20) {
                tooltip.classList.add('tooltip-left');
            }
        }
    });
}

// Check refresh status on page load
document.addEventListener('DOMContentLoaded', function() {
    checkRefreshStatus();
    updateRelativeTimes();
    
    // Update relative times every minute
    setInterval(updateRelativeTimes, 60000);
    
    // Adjust tooltip positions when modal is opened
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                const modal = document.getElementById('channelModal');
                if (modal && modal.style.display === 'block') {
                    // Wait a bit for the modal to fully render
                    setTimeout(adjustTooltipPositions, 100);
                }
            }
        });
    });
    
    const channelModal = document.getElementById('channelModal');
    if (channelModal) {
        observer.observe(channelModal, { attributes: true });
    }
});