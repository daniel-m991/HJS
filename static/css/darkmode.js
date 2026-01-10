// Dark Mode Toggle Script
(function() {
  // Apply dark mode immediately on load to prevent flash
  const darkMode = localStorage.getItem('darkMode') === 'true';
  
  // Apply as soon as possible
  if (darkMode && document.body) {
    document.body.classList.add('dark-mode');
  }
  
  // Also apply when DOM is ready (backup)
  document.addEventListener('DOMContentLoaded', function() {
    if (darkMode) {
      document.body.classList.add('dark-mode');
    }
  });

  // Toggle function
  window.toggleDarkMode = function() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDark);
  };
})();
