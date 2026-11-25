(() => {
  const script = document.currentScript;
  const form = document.querySelector("form.ui-form");
  if (!form) return;

  // Contact details: show only what the chosen way of receiving updates needs.
  const updates = document.getElementById("id_updates_requested");
  const method = document.getElementById("id_contact_method");
  const details = document.querySelector("[data-contact-details]");
  const methodsElement = document.getElementById("contact-methods");
  if (updates && method && details && methodsElement) {
    const codes = JSON.parse(methodsElement.textContent);
    const fieldFor = { EMAIL: "email", TELEPHONE: "telephone", POST: "address" };
    const field = (name) => details.querySelector(`[data-field="${name}"]`);
    const hasError = (name) => Boolean(field(name)?.querySelector(".ui-error"));

    function updateContact() {
      const wanted = updates.checked;
      const chosen = fieldFor[codes[method.value]];
      details.hidden = !wanted;
      field("contact_method").hidden = !wanted;
      for (const name of Object.values(fieldFor)) {
        field(name).hidden = !wanted || (name !== chosen && !hasError(name));
      }
      // The reporter's name is optional context, so it follows the same rule.
      field("name").hidden = !wanted;
    }
    updates.addEventListener("change", updateContact);
    method.addEventListener("change", updateContact);
    updateContact();
  }

  // Photos: reserve a slot, upload directly to the provider, then verify it.
  const section = document.querySelector("[data-photo-upload]");
  const files = document.getElementById("photo-files");
  const status = document.getElementById("photo-status");
  const list = document.getElementById("photo-list");
  const draftInput = document.getElementById("id_photo_draft");
  const slotsInput = document.getElementById("id_photo_slots");
  const send = document.getElementById("send-report");
  if (!section || !files || !status || !list || !draftInput || !slotsInput || !send) {
    return;
  }

  const MAX_PHOTOS = 3;
  const MAX_BYTES = 10_000_000;
  const TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"];
  const token = form.querySelector("input[name=csrfmiddlewaretoken]").value;
  const slots = slotsInput.value ? slotsInput.value.split(",") : [];
  let pending = 0;
  section.hidden = false;

  const post = (url, body) =>
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": token, "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });

  async function problem(response) {
    try {
      return (await response.json()).error;
    } catch {
      return "Please try again.";
    }
  }

  function addItem(text) {
    const item = document.createElement("li");
    item.textContent = text;
    list.append(item);
    return item;
  }

  async function upload(file) {
    const item = addItem(`${file.name}: uploading`);
    try {
      const reserve = await post(script.dataset.photoAuthorizeUrl, {
        draft: draftInput.value || null,
      });
      if (!reserve.ok) throw new Error(await problem(reserve));
      const grant = await reserve.json();
      draftInput.value = grant.draft;

      const body = new FormData();
      for (const [name, value] of Object.entries(grant.fields)) body.append(name, value);
      body.append("file", file);
      const stored = await fetch(grant.upload_url, { method: "POST", body });
      if (!stored.ok) throw new Error("The photo could not be uploaded.");

      const verifyUrl = script.dataset.photoVerifyUrl
        .replace("00000000-0000-0000-0000-000000000000", grant.draft)
        .replace("00000000-0000-0000-0000-000000000000", grant.slot);
      const verified = await post(verifyUrl);
      if (!verified.ok) throw new Error(await problem(verified));

      slots.push(grant.slot);
      slotsInput.value = slots.join(",");
      item.textContent = `${file.name}: ready`;
    } catch (error) {
      item.textContent = `${file.name}: not added. ${error.message}`;
    }
  }

  files.addEventListener("change", async () => {
    const chosen = [...files.files];
    files.value = "";
    const room = MAX_PHOTOS - slots.length - pending;
    status.textContent = "";
    if (chosen.length > room) {
      status.textContent = `You can add up to ${MAX_PHOTOS} photos.`;
    }
    for (const file of chosen.slice(0, Math.max(room, 0))) {
      if (!TYPES.includes(file.type) || file.size > MAX_BYTES) {
        addItem(`${file.name}: not added. Use a JPEG, PNG, WebP or HEIC under 10 MB.`);
        continue;
      }
      pending += 1;
      send.disabled = true;
      await upload(file);
      pending -= 1;
      if (pending === 0) send.disabled = false;
    }
    if (slots.length >= MAX_PHOTOS) files.disabled = true;
    status.textContent = `${slots.length} photo${slots.length === 1 ? "" : "s"} ready to send.`;
  });
})();
