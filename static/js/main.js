/* PP Shop – progressive enhancements for smoother interaction (works without JS too). */
(function () {
  "use strict";

  // Auto-dismiss flash toasts (pause when hovered)
  document.querySelectorAll(".flash-stack .alert").forEach(function (el) {
    var timer;
    var start = function () {
      timer = setTimeout(function () {
        if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(el).close();
      }, 4500);
    };
    el.addEventListener("mouseenter", function () { clearTimeout(timer); });
    el.addEventListener("mouseleave", start);
    start();
  });

  // Quantity steppers: <div data-qty> <button data-step="-1"> <input> <button data-step="1"> </div>
  document.querySelectorAll("[data-qty]").forEach(function (group) {
    var input = group.querySelector("input");
    var minus = group.querySelector('[data-step="-1"]');
    var plus = group.querySelector('[data-step="1"]');

    function syncBounds() {
      var min = parseInt(input.min || "0", 10);
      var max = parseInt(input.max || "99", 10);
      var val = parseInt(input.value, 10) || 0;
      if (minus) minus.disabled = input.disabled || val <= min;
      if (plus) plus.disabled = input.disabled || val >= max;
    }

    group.querySelectorAll("[data-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var min = parseInt(input.min || "0", 10);
        var max = parseInt(input.max || "99", 10);
        var val = (parseInt(input.value, 10) || 0) + parseInt(btn.dataset.step, 10);
        input.value = Math.max(min, Math.min(max, val));
        syncBounds();
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });

    input.addEventListener("input", syncBounds);
    syncBounds();
  });

  // Auto-submit forms marked data-autosubmit with subtle visual feedback
  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    var timer;
    form.addEventListener("change", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var row = form.closest(".cart-item-row, tr");
        if (row) row.classList.add("is-updating");
        form.requestSubmit ? form.requestSubmit() : form.submit();
      }, 380);
    });
  });

  // Confirmation dialogs: <form data-confirm="Are you sure?">
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // Copy-to-clipboard buttons: <button data-copy="text">
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.dataset.copy;
      var label = btn.querySelector("span");
      var icon = btn.querySelector("i");
      var done = function () {
        if (label) {
          var old = label.textContent;
          label.textContent = "Copied!";
          setTimeout(function () { label.textContent = old; }, 1600);
        }
        if (icon) {
          var oldCls = icon.className;
          icon.className = "bi bi-check2";
          setTimeout(function () { icon.className = oldCls; }, 1600);
        }
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
      else { window.prompt("Copy this link:", text); }
    });
  });

  // Image preview + drag-and-drop support
  document.querySelectorAll("input[type=file][data-preview]").forEach(function (input) {
    var target = document.querySelector(input.dataset.preview);
    var dropzone = input.closest(".dropzone");

    function showPreview(file) {
      if (!target || !file || !file.type.startsWith("image/")) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        target.innerHTML = "";
        var img = document.createElement("img");
        img.src = e.target.result;
        img.alt = "Preview";
        target.appendChild(img);
      };
      reader.readAsDataURL(file);
    }

    input.addEventListener("change", function () {
      if (input.files && input.files[0]) showPreview(input.files[0]);
    });

    if (dropzone) {
      ["dragenter", "dragover"].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
          e.preventDefault();
          dropzone.classList.add("is-dragover");
        });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
          e.preventDefault();
          dropzone.classList.remove("is-dragover");
        });
      });
      dropzone.addEventListener("drop", function (e) {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
          input.files = e.dataTransfer.files;
          showPreview(e.dataTransfer.files[0]);
        }
      });
    }
  });

  // Admin sidebar toggle + backdrop (mobile)
  var toggle = document.getElementById("sidebarToggle");
  var sidebar = document.getElementById("adminSidebar");
  var backdrop = document.getElementById("adminBackdrop");
  function closeSidebar() {
    if (sidebar) sidebar.classList.remove("open");
    if (backdrop) backdrop.classList.remove("show");
  }
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      if (backdrop) backdrop.classList.toggle("show", open);
    });
    if (backdrop) backdrop.addEventListener("click", closeSidebar);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeSidebar();
    });
  }
})();
