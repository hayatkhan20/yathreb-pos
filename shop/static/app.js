(() => {
  "use strict";

  const form = document.querySelector("[data-stock-filter-form]");
  if (form) {
    const selects = {
      product: form.querySelector('[data-filter="product"]'),
      brand: form.querySelector('[data-filter="brand"]'),
      article: form.querySelector('[data-filter="article"]'),
      colour: form.querySelector('[data-filter="colour"]'),
      size: form.querySelector('[data-filter="size"]'),
    };
    const fields = {
      brand: form.querySelector('[data-filter-field="brand"]'),
      article: form.querySelector('[data-filter-field="article"]'),
      colour: form.querySelector('[data-filter-field="colour"]'),
      size: form.querySelector('[data-filter-field="size"]'),
    };
    const emptyLabels = {
      brand: "All brands",
      article: "All articles",
      colour: "All colours",
      size: "All sizes",
    };
    const status = document.querySelector("[data-filter-status]");
    let latestRequest = 0;

    function classification() {
      const option = selects.product.selectedOptions[0];
      return option ? option.dataset.classification || "" : "";
    }

    function replaceChoices(level, rows, selectedId) {
      const select = selects[level];
      const choices = document.createDocumentFragment();
      choices.append(new Option(emptyLabels[level], ""));
      rows.forEach((row) => choices.append(new Option(row.name, String(row.id))));
      select.replaceChildren(choices);
      const selectedValue = selectedId === null ? "" : String(selectedId);
      select.value = Array.from(select.options).some((option) => option.value === selectedValue)
        ? selectedValue
        : "";
    }

    function showLevel(level, visible) {
      fields[level].hidden = !visible;
      selects[level].disabled = !visible;
    }

    function clearLevel(level) {
      replaceChoices(level, [], null);
      showLevel(level, false);
    }

    function showLoading(level) {
      const select = selects[level];
      select.replaceChildren(new Option("Loading...", ""));
      fields[level].hidden = false;
      select.disabled = true;
    }

    function renderChoices(data) {
      const productId = data.product_id === null ? "" : String(data.product_id);
      if (selects.product.value !== productId) {
        selects.product.value = productId;
      }
      const structure = data.classification || classification();

      replaceChoices("brand", data.brands, data.brand_id);
      showLevel("brand", Boolean(data.product_id));

      replaceChoices("article", data.articles, data.article_id);
      showLevel("article", structure === "article_colour" && Boolean(data.brand_id));

      replaceChoices("colour", data.colours, data.colour_id);
      showLevel(
        "colour",
        Boolean(data.brand_id) && (structure !== "article_colour" || Boolean(data.article_id)),
      );

      replaceChoices("size", data.sizes, data.size_id);
      showLevel("size", structure === "colour_size" && Boolean(data.colour_id));
    }

    async function loadChoices() {
      const requestNumber = ++latestRequest;
      const parameters = new URLSearchParams();
      Object.entries(selects).forEach(([level, select]) => {
        if (!select.disabled && select.value) {
          parameters.set(`${level}_id`, select.value);
        }
      });
      const url = new URL(form.dataset.childrenUrl, window.location.href);
      url.search = parameters.toString();
      status.textContent = "Loading dependent choices...";
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error("Choice request failed");
        }
        const data = await response.json();
        if (requestNumber !== latestRequest) {
          return;
        }
        renderChoices(data);
        status.textContent = "Choices updated. Apply filters when ready to refresh the stock results.";
      } catch (error) {
        if (requestNumber !== latestRequest) {
          return;
        }
        status.textContent = "Choices could not be loaded automatically. Apply filters to reload them from the server.";
      }
    }

    selects.product.addEventListener("change", () => {
      clearLevel("brand");
      clearLevel("article");
      clearLevel("colour");
      clearLevel("size");
      if (selects.product.value) {
        showLoading("brand");
        loadChoices();
      } else {
        latestRequest += 1;
        status.textContent = "All products selected. Apply filters when ready to refresh the stock results.";
      }
    });

    selects.brand.addEventListener("change", () => {
      clearLevel("article");
      clearLevel("colour");
      clearLevel("size");
      if (!selects.brand.value) {
        latestRequest += 1;
        status.textContent = "All brands selected. Apply filters when ready to refresh the stock results.";
        return;
      }
      if (classification() === "article_colour") {
        showLoading("article");
      } else {
        showLoading("colour");
      }
      loadChoices();
    });

    selects.article.addEventListener("change", () => {
      clearLevel("colour");
      clearLevel("size");
      if (!selects.article.value) {
        latestRequest += 1;
        status.textContent = "All articles selected. Apply filters when ready to refresh the stock results.";
        return;
      }
      showLoading("colour");
      loadChoices();
    });

    selects.colour.addEventListener("change", () => {
      clearLevel("size");
      if (classification() !== "colour_size" || !selects.colour.value) {
        latestRequest += 1;
        status.textContent = "Apply filters when ready to refresh the stock results.";
        return;
      }
      showLoading("size");
      loadChoices();
    });

    status.textContent = "Dependent choices update automatically. Apply filters only when ready to refresh the stock results.";
  }

  const catalogueOpenForms = document.querySelectorAll("[data-catalogue-open-form]");
  if (catalogueOpenForms.length) {
    const addForms = Array.from(document.querySelectorAll("[data-catalogue-add-form]"));

    addForms.forEach((addForm) => {
      addForm.hidden = !addForm.hasAttribute("data-catalogue-add-error");
    });

    catalogueOpenForms.forEach((openForm) => {
      const select = openForm.querySelector("[data-catalogue-select]");
      const fallback = openForm.querySelector("[data-catalogue-open-fallback]");
      if (!select || !fallback) {
        return;
      }
      fallback.hidden = true;

      if (select.dataset.catalogueAddLabel) {
        const addOption = new Option(select.dataset.catalogueAddLabel, "__add_new__");
        addOption.dataset.catalogueAddNew = select.dataset.catalogueSelect;
        select.append(addOption);
      }

      select.addEventListener("change", () => {
        const selected = select.selectedOptions[0];
        const addLevel = selected ? selected.dataset.catalogueAddNew : "";
        if (addLevel) {
          addForms.forEach((addForm) => {
            addForm.hidden = addForm.dataset.catalogueAddForm !== addLevel;
          });
          const addForm = addForms.find(
            (candidate) => candidate.dataset.catalogueAddForm === addLevel,
          );
          const nameInput = addForm ? addForm.querySelector('input[name="name"]') : null;
          if (nameInput) {
            nameInput.focus();
          }
          return;
        }
        addForms.forEach((addForm) => {
          addForm.hidden = true;
        });
        if (select.value || select.dataset.catalogueSelect !== "product") {
          openForm.requestSubmit();
        }
      });
    });
  }

  const stockEntrySelection = document.querySelector("[data-stock-entry-selection]");
  if (stockEntrySelection) {
    const selects = {
      product: stockEntrySelection.querySelector('[data-stock-entry-filter="product"]'),
      brand: stockEntrySelection.querySelector('[data-stock-entry-filter="brand"]'),
      article: stockEntrySelection.querySelector('[data-stock-entry-filter="article"]'),
      colour: stockEntrySelection.querySelector('[data-stock-entry-filter="colour"]'),
      size: stockEntrySelection.querySelector('[data-stock-entry-filter="size"]'),
    };
    const fields = {
      brand: stockEntrySelection.querySelector('[data-stock-entry-field="brand"]'),
      article: stockEntrySelection.querySelector('[data-stock-entry-field="article"]'),
      colour: stockEntrySelection.querySelector('[data-stock-entry-field="colour"]'),
      size: stockEntrySelection.querySelector('[data-stock-entry-field="size"]'),
    };
    const emptyLabels = {
      brand: "Choose brand",
      article: "Choose article",
      colour: "Choose colour",
      size: "Choose size",
    };
    const unitLabels = { metre: "metres", pair: "pairs", piece: "pieces" };
    const fallback = stockEntrySelection.querySelector("[data-stock-entry-fallback]");
    const status = document.querySelector("[data-stock-entry-status]");
    const warning = document.querySelector("[data-stock-entry-warning]");
    const warningHeading = warning.querySelector("[data-stock-warning-heading]");
    const warningCopy = warning.querySelector("[data-stock-warning-copy]");
    const warningLink = warning.querySelector("[data-stock-warning-link]");
    const entryFields = document.querySelector("[data-stock-entry-fields]");
    const entryForm = entryFields.querySelector("[data-stock-entry-form]");
    const entrySummary = entryFields.querySelector("[data-stock-entry-summary]");
    const unitLabel = entryFields.querySelector("[data-stock-entry-unit-label]");
    const quantity = entryForm.querySelector('[name="quantity"]');
    const quantityHint = entryFields.querySelector("[data-stock-entry-quantity-hint]");
    let latestStockRequest = 0;
    let loadingChoices = false;
    let choiceLoadFailed = false;

    function selectedOption(level) {
      return selects[level].selectedOptions[0] || null;
    }

    function selectedText(level) {
      const option = selectedOption(level);
      return option && option.value ? option.textContent.trim() : "";
    }

    function classification() {
      const option = selectedOption("product");
      return option ? option.dataset.classification || "" : "";
    }

    function productUnit() {
      const option = selectedOption("product");
      return option ? option.dataset.unit || "" : "";
    }

    function suggestedUnit() {
      const option = selectedOption("product");
      return option ? option.dataset.suggestedUnit || "" : "";
    }

    function choiceCount(level) {
      return Array.from(selects[level].options).filter((option) => option.value).length;
    }

    function replaceChoices(level, rows, selectedId) {
      const select = selects[level];
      const choices = document.createDocumentFragment();
      choices.append(new Option(emptyLabels[level], ""));
      rows.forEach((row) => choices.append(new Option(row.name, String(row.id))));
      select.replaceChildren(choices);
      const selectedValue = selectedId === null ? "" : String(selectedId);
      select.value = Array.from(select.options).some((option) => option.value === selectedValue)
        ? selectedValue
        : "";
    }

    function showLevel(level, visible) {
      fields[level].hidden = !visible;
      selects[level].disabled = !visible;
    }

    function clearLevel(level) {
      replaceChoices(level, [], null);
      showLevel(level, false);
    }

    function showLoading(level) {
      selects[level].replaceChildren(new Option("Loading...", ""));
      fields[level].hidden = false;
      selects[level].disabled = true;
    }

    function managementUrl(parameters, fragment) {
      const url = new URL(stockEntrySelection.dataset.catalogueUrl, window.location.href);
      Object.entries(parameters).forEach(([key, value]) => {
        if (value) {
          url.searchParams.set(`${key}_id`, value);
        }
      });
      url.hash = fragment;
      return url.toString();
    }

    function setWarning(heading, copy, linkText, parameters, fragment) {
      warningHeading.textContent = heading;
      warningCopy.textContent = copy;
      warningLink.textContent = linkText;
      warningLink.href = managementUrl(parameters, fragment);
      warning.hidden = false;
    }

    function updateWarning() {
      const productId = selects.product.value;
      const brandId = selects.brand.value;
      const articleId = selects.article.value;
      const colourId = selects.colour.value;
      const structure = classification();
      warning.hidden = true;

      if (!productId) {
        return;
      }
      if (!productUnit()) {
        const proposal = unitLabels[suggestedUnit()] || "the proposed unit";
        setWarning(
          "Confirm this product’s stock unit",
          `The recorded suggestion is ${proposal}, but it remains a proposal. Stock entry is unavailable until you explicitly choose pairs or pieces.`,
          "Review and confirm unit",
          { product: productId },
          "product-editor",
        );
        return;
      }
      if (loadingChoices || choiceLoadFailed) {
        return;
      }
      if (choiceCount("brand") === 0) {
        setWarning(
          "Add a brand first",
          "This product has no brands.",
          "Manage product",
          { product: productId },
          "brands-section",
        );
        return;
      }
      if (!brandId) {
        return;
      }
      if (structure === "article_colour") {
        if (choiceCount("article") === 0) {
          setWarning(
            "Add an article first",
            `${selectedText("brand")} has no articles.`,
            "Manage brand",
            { product: productId, brand: brandId },
            "articles-section",
          );
          return;
        }
        if (!articleId) {
          return;
        }
      }
      if (choiceCount("colour") === 0) {
        const parentName = structure === "article_colour" ? "article" : "brand";
        setWarning(
          "Add a colour first",
          `The selected ${parentName} has no colours.`,
          "Manage colours",
          { product: productId, brand: brandId, article: articleId },
          "colours-section",
        );
        return;
      }
      if (!colourId) {
        return;
      }
      if (structure === "colour_size" && choiceCount("size") === 0) {
        setWarning(
          "Add a size first",
          `${selectedText("colour")} has no sizes.`,
          "Manage sizes",
          { product: productId, brand: brandId, colour: colourId },
          "sizes-section",
        );
      }
    }

    function syncEntryChain() {
      Object.entries(selects).forEach(([level, select]) => {
        entryForm.querySelector(`[data-stock-entry-chain="${level}"]`).value = select.value;
      });
    }

    function updateEntryFields() {
      syncEntryChain();
      const structure = classification();
      const unit = productUnit();
      const complete = Boolean(
        selects.product.value
        && selects.brand.value
        && selects.colour.value
        && (structure !== "article_colour" || selects.article.value)
        && (structure !== "colour_size" || selects.size.value),
      );
      entryFields.hidden = !complete || !unit;
      entryFields.dataset.stockEntryReady = entryFields.hidden ? "false" : "true";

      if (!entryFields.hidden) {
        const chain = ["product", "brand"];
        if (structure === "article_colour") {
          chain.push("article");
        }
        chain.push("colour");
        if (structure === "colour_size") {
          chain.push("size");
        }
        entrySummary.textContent = chain.map(selectedText).join(" · ");
        unitLabel.textContent = unitLabels[unit] || unit;
        quantity.placeholder = unit === "metre" ? "0.000" : "0";
        quantityHint.textContent = unit === "metre"
          ? "The database can store up to three decimal places. The permitted cutting increment remains open."
          : `Enter a whole number of ${unitLabels[unit] || unit}.`;
      }
      updateWarning();
    }

    function updateReadyStatus() {
      status.textContent = entryFields.hidden
        ? "Choose the next available level. Dependent choices update automatically."
        : "Selection complete. Enter the stock details and save once.";
    }

    function renderChoices(data) {
      const productId = data.product_id === null ? "" : String(data.product_id);
      if (selects.product.value !== productId) {
        selects.product.value = productId;
      }
      const option = selectedOption("product");
      if (option) {
        option.dataset.unit = data.unit || "";
        option.dataset.suggestedUnit = data.suggested_unit || "";
      }
      const structure = data.classification || classification();

      replaceChoices("brand", data.brands, data.brand_id);
      showLevel("brand", Boolean(data.product_id));
      replaceChoices("article", data.articles, data.article_id);
      showLevel("article", structure === "article_colour" && Boolean(data.brand_id));
      replaceChoices("colour", data.colours, data.colour_id);
      showLevel(
        "colour",
        Boolean(data.brand_id) && (structure !== "article_colour" || Boolean(data.article_id)),
      );
      replaceChoices("size", data.sizes, data.size_id);
      showLevel("size", structure === "colour_size" && Boolean(data.colour_id));
    }

    async function loadStockChoices() {
      const requestNumber = ++latestStockRequest;
      const parameters = new URLSearchParams();
      Object.entries(selects).forEach(([level, select]) => {
        if (!select.disabled && select.value) {
          parameters.set(`${level}_id`, select.value);
        }
      });
      const url = new URL(stockEntrySelection.dataset.childrenUrl, window.location.href);
      url.search = parameters.toString();
      status.textContent = "Loading dependent choices...";
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error("Choice request failed");
        }
        const data = await response.json();
        if (requestNumber !== latestStockRequest) {
          return;
        }
        renderChoices(data);
        loadingChoices = false;
        choiceLoadFailed = false;
        fallback.hidden = true;
        updateEntryFields();
        updateReadyStatus();
      } catch (_error) {
        if (requestNumber !== latestStockRequest) {
          return;
        }
        loadingChoices = false;
        choiceLoadFailed = true;
        fallback.hidden = false;
        updateEntryFields();
        status.textContent = "Choices could not be loaded automatically. Use Open selection to reload them from the server.";
      }
    }

    function beginChoiceLoad(level) {
      loadingChoices = true;
      choiceLoadFailed = false;
      fallback.hidden = true;
      showLoading(level);
      updateEntryFields();
      loadStockChoices();
    }

    selects.product.addEventListener("change", () => {
      clearLevel("brand");
      clearLevel("article");
      clearLevel("colour");
      clearLevel("size");
      if (selects.product.value) {
        beginChoiceLoad("brand");
      } else {
        latestStockRequest += 1;
        loadingChoices = false;
        choiceLoadFailed = false;
        updateEntryFields();
        updateReadyStatus();
      }
    });

    selects.brand.addEventListener("change", () => {
      clearLevel("article");
      clearLevel("colour");
      clearLevel("size");
      if (!selects.brand.value) {
        latestStockRequest += 1;
        loadingChoices = false;
        choiceLoadFailed = false;
        updateEntryFields();
        updateReadyStatus();
        return;
      }
      beginChoiceLoad(classification() === "article_colour" ? "article" : "colour");
    });

    selects.article.addEventListener("change", () => {
      clearLevel("colour");
      clearLevel("size");
      if (!selects.article.value) {
        latestStockRequest += 1;
        loadingChoices = false;
        choiceLoadFailed = false;
        updateEntryFields();
        updateReadyStatus();
        return;
      }
      beginChoiceLoad("colour");
    });

    selects.colour.addEventListener("change", () => {
      clearLevel("size");
      if (classification() === "colour_size" && selects.colour.value) {
        beginChoiceLoad("size");
        return;
      }
      latestStockRequest += 1;
      loadingChoices = false;
      choiceLoadFailed = false;
      updateEntryFields();
      updateReadyStatus();
    });

    selects.size.addEventListener("change", () => {
      latestStockRequest += 1;
      loadingChoices = false;
      choiceLoadFailed = false;
      updateEntryFields();
      updateReadyStatus();
    });

    fallback.hidden = true;
    updateEntryFields();
    updateReadyStatus();
  }

  const billingForm = document.querySelector("[data-billing-form]");
  if (billingForm) {
    const selects = {
      product: billingForm.querySelector('[data-billing-filter="product"]'),
      brand: billingForm.querySelector('[data-billing-filter="brand"]'),
      article: billingForm.querySelector('[data-billing-filter="article"]'),
      colour: billingForm.querySelector('[data-billing-filter="colour"]'),
      size: billingForm.querySelector('[data-billing-filter="size"]'),
    };
    const fields = {
      brand: billingForm.querySelector('[data-billing-field="brand"]'),
      article: billingForm.querySelector('[data-billing-field="article"]'),
      colour: billingForm.querySelector('[data-billing-field="colour"]'),
      size: billingForm.querySelector('[data-billing-field="size"]'),
    };
    const emptyLabels = {
      brand: "Choose brand",
      article: "Choose article",
      colour: "Choose colour",
      size: "Choose size",
    };
    const unitLabels = { metre: "metres", pair: "pairs", piece: "pieces" };
    const fallback = billingForm.querySelector("[data-billing-fallback]");
    const status = billingForm.querySelector("[data-billing-status]");
    const variantPanel = billingForm.querySelector("[data-billing-variant]");
    const variantError = billingForm.querySelector("[data-variant-error]");
    const variantDescription = billingForm.querySelector("[data-variant-description]");
    const variantUnit = billingForm.querySelector("[data-variant-unit]");
    const variantBalance = billingForm.querySelector("[data-variant-balance]");
    const variantDefault = billingForm.querySelector("[data-variant-default]");
    const defaultPrice = billingForm.querySelector("[data-default-price]");
    const linePrice = billingForm.querySelector("[data-line-price]");
    const lineQuantity = billingForm.querySelector("[data-line-quantity]");
    const quantityHint = billingForm.querySelector("[data-line-quantity-hint]");
    const negativeWarning = billingForm.querySelector("[data-negative-warning]");
    const addProductButton = billingForm.querySelector("[data-add-bill-line]");
    const billItemsInput = billingForm.querySelector("[data-bill-items]");
    const billLines = billingForm.querySelector("[data-bill-lines]");
    const lineCount = billingForm.querySelector("[data-bill-line-count]");
    const confirmation = document.querySelector("[data-billing-confirmation]");
    const confirmationHeading = confirmation.querySelector("[data-billing-confirmation-heading]");
    const confirmationDetail = confirmation.querySelector("[data-billing-confirmation-detail]");
    const currentBillSummary = document.querySelector("[data-current-bill-summary]");
    const currentBillCount = currentBillSummary.querySelector("[data-current-bill-count]");
    const currentBillItems = currentBillSummary.querySelector("[data-current-bill-items]");
    const currentBillSubtotal = currentBillSummary.querySelector("[data-current-bill-subtotal]");
    const discountInput = billingForm.querySelector("[data-bill-discount]");
    const paidInput = billingForm.querySelector("[data-bill-paid]");
    const paidWasEditedInput = billingForm.querySelector("[data-paid-was-edited]");
    const subtotalOutput = billingForm.querySelector("[data-total-subtotal]");
    const discountOutput = billingForm.querySelector("[data-total-discount]");
    const grandOutput = billingForm.querySelector("[data-total-grand]");
    const paidOutput = billingForm.querySelector("[data-total-paid]");
    const remainingOutput = billingForm.querySelector("[data-total-remaining]");
    const clothOptions = billingForm.querySelector("[data-cloth-options]");
    const clothQuestion = clothOptions ? clothOptions.querySelector("[data-cloth-question]") : null;
    const currentFabricOptions = clothOptions
      ? clothOptions.querySelector("[data-current-fabric-options]") : null;
    const clothAlternatives = clothOptions
      ? clothOptions.querySelector("[data-cloth-alternatives]") : null;
    const differentClothButton = clothOptions
      ? clothOptions.querySelector("[data-use-different-cloth]") : null;
    const saleModeInputs = Array.from(billingForm.querySelectorAll("[data-sale-mode]"));
    const saleModeSections = Array.from(
      billingForm.querySelectorAll("[data-sale-mode-section]"),
    );
    const saleModeStatus = billingForm.querySelector("[data-sale-mode-status]");
    const customerSearch = billingForm.querySelector("[data-billing-customer-search]");
    const customerResults = billingForm.querySelector("[data-billing-customer-results]");
    const customerStatus = billingForm.querySelector("[data-billing-customer-status]");
    const customerSearchFallback = billingForm.querySelector("[data-customer-search-fallback]");
    const customerDialogLink = billingForm.querySelector("[data-open-customer-dialog]");
    const customerDialog = document.querySelector("[data-customer-dialog]");
    const inlineCustomerForm = customerDialog
      ? customerDialog.querySelector("[data-inline-customer-form]") : null;
    const inlineCustomerError = customerDialog
      ? customerDialog.querySelector("[data-inline-customer-error]") : null;
    const actionInput = document.createElement("input");
    actionInput.type = "hidden";
    actionInput.name = "action";
    actionInput.dataset.billingActionInput = "";
    billingForm.querySelectorAll('button[name="action"]').forEach((button) => {
      button.dataset.billingAction = button.value;
      button.removeAttribute("name");
    });
    billingForm.append(actionInput);
    let latestBillingRequest = 0;
    let currentVariant = null;
    let paidWasEdited = paidInput.dataset.paidSupplied === "true";
    let previousFabricCount = currentFabricOptions
      ? currentFabricOptions.querySelectorAll("[data-current-fabric-option]").length : 0;
    let alternativeClothSelected = Boolean(
      clothOptions
      && previousFabricCount > 0
      && clothOptions.dataset.alternateSelected === "true"
    );

    function submitBillingAction(value) {
      const submitter = document.createElement("button");
      submitter.type = "submit";
      submitter.hidden = true;
      submitter.formNoValidate = true;
      submitter.dataset.billingAction = value;
      billingForm.append(submitter);
      billingForm.requestSubmit(submitter);
    }

    function hideCustomerResults() {
      if (!customerResults || !customerSearch) return;
      customerResults.hidden = true;
      customerSearch.setAttribute("aria-expanded", "false");
    }

    function renderCustomerResults(customers) {
      if (!customerResults || !customerSearch || !customerStatus) return;
      customerResults.replaceChildren();
      if (!customers.length) {
        hideCustomerResults();
        customerStatus.textContent = "No matching customers found.";
        return;
      }
      customers.forEach((customer) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "customer-match";
        option.setAttribute("role", "option");
        const identity = document.createElement("strong");
        identity.textContent = `${customer.customer_number} · ${customer.name}`;
        const mobile = document.createElement("span");
        mobile.textContent = customer.primary_mobile;
        option.append(identity, mobile);
        option.addEventListener("click", () => {
          customerStatus.textContent = `Selecting ${customer.name}…`;
          hideCustomerResults();
          submitBillingAction(`select_customer:${customer.id}`);
        });
        customerResults.append(option);
      });
      customerResults.hidden = false;
      customerSearch.setAttribute("aria-expanded", "true");
      customerStatus.textContent = `${customers.length} matching customer${customers.length === 1 ? "" : "s"}.`;
    }

    let customerSearchTimer = null;
    let customerSearchRequest = null;
    async function loadCustomerResults() {
      if (!customerSearch || !customerResults || !customerStatus) return;
      const query = customerSearch.value.trim();
      if (query.length < 2) {
        if (customerSearchRequest) customerSearchRequest.abort();
        hideCustomerResults();
        customerStatus.textContent = "Type at least 2 characters to see matching customers.";
        return;
      }
      if (customerSearchRequest) customerSearchRequest.abort();
      customerSearchRequest = new AbortController();
      customerStatus.textContent = "Searching customers…";
      try {
        const url = new URL(billingForm.dataset.customerUrl, window.location.href);
        url.searchParams.set("q", query);
        const response = await fetch(url, {
          headers: { Accept: "application/json" },
          signal: customerSearchRequest.signal,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Customer search failed.");
        renderCustomerResults(payload.customers || []);
      } catch (error) {
        if (error.name === "AbortError") return;
        hideCustomerResults();
        customerStatus.textContent = "Customer search is unavailable. Use Search customers.";
      }
    }

    if (customerSearch && customerResults && customerStatus) {
      customerSearch.addEventListener("input", () => {
        window.clearTimeout(customerSearchTimer);
        customerSearchTimer = window.setTimeout(loadCustomerResults, 180);
      });
      customerSearch.addEventListener("keydown", (event) => {
        if (event.key === "Escape") hideCustomerResults();
        if (event.key === "ArrowDown" && !customerResults.hidden) {
          const first = customerResults.querySelector("button");
          if (first) {
            event.preventDefault();
            first.focus();
          }
        }
      });
      document.addEventListener("click", (event) => {
        if (!event.target.closest(".customer-search-field")) hideCustomerResults();
      });
      if (customerSearchFallback) customerSearchFallback.hidden = true;
    }

    if (
      customerDialogLink
      && customerDialog
      && inlineCustomerForm
      && typeof customerDialog.showModal === "function"
    ) {
      customerDialogLink.addEventListener("click", (event) => {
        event.preventDefault();
        if (inlineCustomerError) inlineCustomerError.hidden = true;
        customerDialog.showModal();
        const nameInput = inlineCustomerForm.querySelector('[name="name"]');
        if (nameInput) nameInput.focus();
      });
      customerDialog.querySelectorAll("[data-close-customer-dialog]").forEach((button) => {
        button.addEventListener("click", () => customerDialog.close());
      });
      inlineCustomerForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const saveButton = inlineCustomerForm.querySelector("[data-save-inline-customer]");
        if (saveButton) saveButton.disabled = true;
        if (inlineCustomerError) inlineCustomerError.hidden = true;
        try {
          const response = await fetch(inlineCustomerForm.action, {
            method: "POST",
            headers: { Accept: "application/json" },
            body: new FormData(inlineCustomerForm),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "The customer could not be added.");
          inlineCustomerForm.reset();
          customerDialog.close();
          submitBillingAction(`select_customer:${payload.customer.id}`);
        } catch (error) {
          if (inlineCustomerError) {
            inlineCustomerError.textContent = error.message;
            inlineCustomerError.hidden = false;
            inlineCustomerError.focus();
          }
        } finally {
          if (saveButton) saveButton.disabled = false;
        }
      });
    }

    function applySaleMode() {
      const selected = saleModeInputs.find((input) => input.checked);
      const mode = selected ? selected.value : "product";
      saleModeSections.forEach((section) => {
        const sectionType = section.dataset.saleModeSection;
        const visible = (sectionType === "products" && mode !== "tailoring")
          || (sectionType === "tailoring" && mode !== "product");
        section.classList.toggle("sale-mode-hidden", !visible);
      });
      if (saleModeStatus) {
        const messages = {
          product: "Customer details are optional unless a balance will remain.",
          combined: "Add the products and stitching services to one combined bill.",
          tailoring: "Select the customer, measurements, garment, and cloth source.",
        };
        saleModeStatus.textContent = messages[mode] || "";
      }
    }

    saleModeInputs.forEach((input) => input.addEventListener("change", applySaleMode));

    function selectedOption(level) {
      return selects[level].selectedOptions[0] || null;
    }

    function classification() {
      const option = selectedOption("product");
      return option ? option.dataset.classification || "" : "";
    }

    function productUnit() {
      const option = selectedOption("product");
      return option ? option.dataset.unit || "" : "";
    }

    function completeChain() {
      const structure = classification();
      return Boolean(
        selects.product.value
        && productUnit()
        && selects.brand.value
        && selects.colour.value
        && (structure !== "article_colour" || selects.article.value)
        && (structure !== "colour_size" || selects.size.value)
      );
    }

    function replaceChoices(level, rows, selectedId) {
      const choices = document.createDocumentFragment();
      choices.append(new Option(emptyLabels[level], ""));
      rows.forEach((row) => choices.append(new Option(row.name, String(row.id))));
      selects[level].replaceChildren(choices);
      const selectedValue = selectedId === null ? "" : String(selectedId);
      selects[level].value = Array.from(selects[level].options).some(
        (option) => option.value === selectedValue,
      ) ? selectedValue : "";
    }

    function showLevel(level, visible) {
      fields[level].hidden = !visible;
      selects[level].disabled = !visible;
    }

    function clearLevel(level) {
      replaceChoices(level, [], null);
      showLevel(level, false);
    }

    function showLoading(level) {
      selects[level].replaceChildren(new Option("Loading...", ""));
      fields[level].hidden = false;
      selects[level].disabled = true;
    }

    function renderChoices(data) {
      const productId = data.product_id === null ? "" : String(data.product_id);
      selects.product.value = productId;
      const productOption = selectedOption("product");
      if (productOption) {
        productOption.dataset.unit = data.unit || "";
        productOption.dataset.suggestedUnit = data.suggested_unit || "";
      }
      const structure = data.classification || classification();
      replaceChoices("brand", data.brands, data.brand_id);
      showLevel("brand", Boolean(data.product_id));
      replaceChoices("article", data.articles, data.article_id);
      showLevel("article", structure === "article_colour" && Boolean(data.brand_id));
      replaceChoices("colour", data.colours, data.colour_id);
      showLevel(
        "colour",
        Boolean(data.brand_id) && (structure !== "article_colour" || Boolean(data.article_id)),
      );
      replaceChoices("size", data.sizes, data.size_id);
      showLevel("size", structure === "colour_size" && Boolean(data.colour_id));
    }

    function hierarchyParameters() {
      const parameters = new URLSearchParams();
      Object.entries(selects).forEach(([level, select]) => {
        if (!select.disabled && select.value) {
          parameters.set(`${level}_id`, select.value);
        }
      });
      return parameters;
    }

    function hideVariant(message = "") {
      currentVariant = null;
      variantPanel.hidden = true;
      variantPanel.dataset.variantReady = "false";
      negativeWarning.hidden = true;
      if (message) {
        variantError.textContent = message;
        variantError.hidden = false;
      } else {
        variantError.hidden = true;
      }
    }

    function showVariant(data) {
      currentVariant = data;
      variantPanel.hidden = false;
      variantPanel.dataset.variantReady = "true";
      variantPanel.dataset.variantId = String(data.id);
      variantPanel.dataset.product = data.product;
      variantPanel.dataset.isFabric = data.is_fabric ? "true" : "false";
      variantPanel.dataset.currentBalance = String(data.current_balance);
      variantPanel.dataset.unit = data.unit;
      variantPanel.dataset.defaultPrice = data.default_selling_price === null
        ? ""
        : String(data.default_selling_price);
      variantDescription.textContent = data.description;
      variantUnit.textContent = unitLabels[data.unit] || data.unit;
      variantBalance.textContent = data.current_balance_display;
      variantBalance.classList.toggle("negative-value", data.current_balance < 0);
      variantDefault.textContent = data.default_selling_price_display === null
        ? "Not set"
        : `PKR ${data.default_selling_price_display}`;
      defaultPrice.value = data.default_selling_price_input;
      linePrice.value = data.default_selling_price_input;
      lineQuantity.value = "";
      lineQuantity.placeholder = data.unit === "metre" ? "0.000" : "0";
      quantityHint.textContent = data.unit === "metre"
        ? "Metres allow up to three decimal places."
        : `${unitLabels[data.unit] || data.unit} require a whole number.`;
      variantError.hidden = true;
      updateNegativeWarning();
    }

    async function loadVariant(requestNumber) {
      if (!completeChain()) {
        hideVariant();
        if (selects.product.value && !productUnit()) {
          status.textContent = "Confirm this Product’s stock unit in the catalogue before billing it.";
        } else {
          status.textContent = "Choose the next available hierarchy level.";
        }
        return;
      }
      const url = new URL(billingForm.dataset.variantUrl, window.location.href);
      url.search = hierarchyParameters().toString();
      status.textContent = "Loading the selected product...";
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await response.json();
        if (requestNumber !== latestBillingRequest) {
          return;
        }
        if (!response.ok) {
          throw new Error(data.error || "The exact variant could not be loaded.");
        }
        showVariant(data);
        status.textContent = "Product ready. Enter a price and quantity, then add it to the bill.";
      } catch (error) {
        if (requestNumber !== latestBillingRequest) {
          return;
        }
        hideVariant(error.message || "The exact variant could not be loaded.");
        fallback.hidden = false;
        status.textContent = "Automatic loading failed. Use Open selection for the server-rendered fallback.";
      }
    }

    async function loadBillingChoices() {
      const requestNumber = ++latestBillingRequest;
      const url = new URL(billingForm.dataset.childrenUrl, window.location.href);
      url.search = hierarchyParameters().toString();
      status.textContent = "Loading dependent choices...";
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error("Choice request failed");
        }
        const data = await response.json();
        if (requestNumber !== latestBillingRequest) {
          return;
        }
        renderChoices(data);
        fallback.hidden = true;
        await loadVariant(requestNumber);
      } catch (_error) {
        if (requestNumber !== latestBillingRequest) {
          return;
        }
        hideVariant();
        fallback.hidden = false;
        status.textContent = "Choices could not be loaded automatically. Use Open selection to continue safely.";
      }
    }

    function beginChoiceLoad(level) {
      hideVariant();
      fallback.hidden = true;
      showLoading(level);
      loadBillingChoices();
    }

    function parseMoney(value) {
      const match = String(value).trim().match(/^([0-9]{1,15})(?:\.([0-9]{1,2}))?$/);
      if (!match) {
        return null;
      }
      return BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0") || "0");
    }

    function formatMoney(value, grouping = true) {
      const whole = value / 100n;
      const paisa = String(value % 100n).padStart(2, "0");
      const integer = grouping
        ? String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
        : String(whole);
      return `${integer}.${paisa}`;
    }

    function parseQuantity(value, unit) {
      const match = String(value).trim().match(/^([0-9]{1,12})(?:\.([0-9]{1,3}))?$/);
      if (!match) {
        return null;
      }
      const scaled = BigInt(match[1]) * 1000n
        + BigInt((match[2] || "").padEnd(3, "0") || "0");
      if (scaled <= 0n || scaled > 1000000000n) {
        return null;
      }
      if (unit !== "metre" && scaled % 1000n !== 0n) {
        return null;
      }
      return scaled;
    }

    function formatQuantity(value) {
      const sign = value < 0n ? "-" : "";
      const absolute = value < 0n ? -value : value;
      const whole = absolute / 1000n;
      const fraction = String(absolute % 1000n).padStart(3, "0").replace(/0+$/, "");
      return fraction ? `${sign}${whole}.${fraction}` : `${sign}${whole}`;
    }

    function draftItems() {
      try {
        const items = JSON.parse(billItemsInput.value || "[]");
        return Array.isArray(items) ? items : [];
      } catch (_error) {
        return [];
      }
    }

    function existingDraftQuantity(variantId) {
      return draftItems().reduce((total, item) => {
        if (String(item.variant_id) !== String(variantId)) {
          return total;
        }
        return total + (parseQuantity(item.quantity, currentVariant.unit) || 0n);
      }, 0n);
    }

    function updateNegativeWarning() {
      if (!currentVariant) {
        negativeWarning.hidden = true;
        return;
      }
      const quantity = parseQuantity(lineQuantity.value, currentVariant.unit);
      if (quantity === null) {
        negativeWarning.hidden = true;
        return;
      }
      const projected = BigInt(currentVariant.current_balance)
        - existingDraftQuantity(currentVariant.id)
        - quantity;
      negativeWarning.hidden = projected >= 0n;
      if (projected < 0n) {
        negativeWarning.textContent = `Recorded balance would become ${formatQuantity(projected)} ${unitLabels[currentVariant.unit] || currentVariant.unit}. The sale is still allowed and the negative balance will be recorded.`;
      }
    }

    function updateTotals() {
      const subtotal = Array.from(billLines.querySelectorAll("[data-bill-line]")).reduce(
        (total, row) => total + BigInt(row.dataset.lineTotal || "0"),
        0n,
      );
      const parsedDiscount = parseMoney(discountInput.value);
      const discount = parsedDiscount !== null && parsedDiscount <= subtotal ? parsedDiscount : 0n;
      const grand = subtotal - discount;
      if (!paidWasEdited) {
        paidInput.value = formatMoney(grand, false);
      }
      const parsedPaid = parseMoney(paidInput.value);
      const paid = parsedPaid === null ? 0n : parsedPaid;
      const remaining = paid >= grand ? 0n : grand - paid;
      subtotalOutput.textContent = formatMoney(subtotal);
      discountOutput.textContent = formatMoney(discount);
      grandOutput.textContent = formatMoney(grand);
      paidOutput.textContent = formatMoney(paid);
      remainingOutput.textContent = formatMoney(remaining);
    }

    function updateCurrentBillSummary() {
      const rows = Array.from(billLines.querySelectorAll("[data-bill-line]"));
      currentBillSummary.hidden = rows.length === 0;
      currentBillCount.textContent = `${rows.length} item${rows.length === 1 ? "" : "s"}`;
      currentBillItems.replaceChildren();
      let subtotal = 0n;
      rows.forEach((row) => {
        subtotal += BigInt(row.dataset.lineTotal || "0");
        const item = document.createElement("li");
        const description = document.createElement("span");
        description.textContent = row.dataset.summaryDescription || "Bill item";
        const quantity = document.createElement("strong");
        quantity.textContent = row.dataset.summaryQuantity || "";
        item.append(description, quantity);
        currentBillItems.append(item);
      });
      currentBillSubtotal.textContent = formatMoney(subtotal);
    }

    function showProductConfirmation(item) {
      confirmationHeading.textContent = `${item.product} added to the current bill.`;
      confirmationDetail.textContent = `${item.description} · ${item.quantity} ${unitLabels[item.unit] || item.unit}`;
      confirmation.hidden = false;
      window.requestAnimationFrame(() => {
        confirmation.focus({ preventScroll: true });
        confirmation.scrollIntoView({ block: "nearest" });
      });
    }

    function appendBillRow(item, lineTotal, projected) {
      const empty = billLines.querySelector("[data-empty-bill]");
      if (empty) {
        empty.remove();
      }
      const row = document.createElement("tr");
      row.dataset.billLine = "";
      row.dataset.lineType = "product";
      row.dataset.productLineNumber = String(draftItems().length);
      row.dataset.isFabric = currentVariant.is_fabric ? "true" : "false";
      row.dataset.summaryDescription = currentVariant.description;
      row.dataset.summaryQuantity = `${item.quantity} ${unitLabels[currentVariant.unit] || currentVariant.unit}`;
      row.dataset.lineTotal = String(lineTotal);

      const typeCell = document.createElement("td");
      typeCell.textContent = "Product";

      const descriptionCell = document.createElement("td");
      const description = document.createElement("strong");
      description.textContent = currentVariant.description;
      descriptionCell.append(description);
      if (projected < 0n) {
        const warning = document.createElement("span");
        warning.className = "negative-note";
        warning.textContent = `Recorded balance after this draft line: ${formatQuantity(projected)} ${unitLabels[currentVariant.unit] || currentVariant.unit}. Sale remains allowed.`;
        descriptionCell.append(warning);
      }

      const quantityCell = document.createElement("td");
      quantityCell.className = "number";
      quantityCell.textContent = `${item.quantity} ${unitLabels[currentVariant.unit] || currentVariant.unit}`;
      const unitCell = document.createElement("td");
      unitCell.textContent = unitLabels[currentVariant.unit] || currentVariant.unit;
      const priceCell = document.createElement("td");
      priceCell.className = "number";
      priceCell.textContent = `PKR ${formatMoney(BigInt(item.unit_price))}`;
      const totalCell = document.createElement("td");
      totalCell.className = "number";
      totalCell.textContent = `PKR ${formatMoney(lineTotal)}`;
      const clothCell = document.createElement("td");
      clothCell.className = "empty-copy";
      clothCell.textContent = "Not applicable";
      const actionCell = document.createElement("td");
      const remove = document.createElement("button");
      remove.type = "submit";
      remove.value = `remove_line:${draftItems().length - 1}`;
      remove.dataset.billingAction = remove.value;
      remove.className = "secondary small";
      remove.formNoValidate = true;
      remove.dataset.removeBillLine = String(draftItems().length - 1);
      remove.textContent = "Remove";
      actionCell.append(remove);
      row.append(typeCell, descriptionCell, quantityCell, unitCell, priceCell, totalCell, clothCell, actionCell);
      billLines.append(row);
    }

    function makeCurrentFabricOption(row) {
      const label = document.createElement("label");
      label.className = "cloth-option";
      label.dataset.currentFabricOption = "";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "cloth_choice";
      input.value = `current:${row.dataset.productLineNumber}`;
      const copy = document.createElement("span");
      const description = document.createElement("strong");
      description.textContent = row.dataset.summaryDescription;
      const quantity = document.createElement("small");
      quantity.textContent = row.dataset.summaryQuantity;
      copy.append(description, quantity);
      label.append(input, copy);
      return label;
    }

    function refreshClothOptions(initial) {
      if (!clothOptions) {
        return;
      }
      const fabricRows = Array.from(billLines.querySelectorAll(
        '[data-bill-line][data-line-type="product"][data-is-fabric="true"]',
      ));
      const selected = clothOptions.querySelector('input[name="cloth_choice"]:checked');
      let selectedChoice = selected ? selected.value : "";
      currentFabricOptions.replaceChildren(
        ...fabricRows.map((row) => makeCurrentFabricOption(row)),
      );

      if (!initial && fabricRows.length !== previousFabricCount && !alternativeClothSelected) {
        selectedChoice = fabricRows.length === 1
          ? `current:${fabricRows[0].dataset.productLineNumber}` : "";
      }
      if (fabricRows.length === 1 && !selectedChoice && !alternativeClothSelected) {
        selectedChoice = `current:${fabricRows[0].dataset.productLineNumber}`;
      }
      if (fabricRows.length === 0) {
        clothQuestion.textContent = "Cloth source";
        differentClothButton.hidden = true;
        clothAlternatives.hidden = false;
        if (!selectedChoice || selectedChoice.startsWith("current:")) {
          selectedChoice = "customer";
        }
      } else {
        clothQuestion.textContent = fabricRows.length === 1
          ? "Fabric from this bill"
          : "Which fabric is being used for this garment?";
        differentClothButton.hidden = false;
        clothAlternatives.hidden = !alternativeClothSelected;
      }

      const selectedInput = Array.from(
        clothOptions.querySelectorAll('input[name="cloth_choice"]'),
      ).find((input) => input.value === selectedChoice);
      if (selectedInput) {
        selectedInput.checked = true;
      } else {
        clothOptions.querySelectorAll('input[name="cloth_choice"]').forEach((input) => {
          input.checked = false;
        });
      }
      previousFabricCount = fabricRows.length;
    }

    if (clothOptions) {
      differentClothButton.addEventListener("click", () => {
        alternativeClothSelected = true;
        clothAlternatives.hidden = false;
        const firstAlternative = clothAlternatives.querySelector('input[name="cloth_choice"]');
        if (firstAlternative) {
          firstAlternative.focus();
        }
      });
      clothOptions.addEventListener("change", (event) => {
        if (!event.target.matches('input[name="cloth_choice"]')) {
          return;
        }
        alternativeClothSelected = !event.target.value.startsWith("current:");
        clothAlternatives.hidden = previousFabricCount > 0 && !alternativeClothSelected;
      });
    }

    selects.product.addEventListener("change", () => {
      clearLevel("brand");
      clearLevel("article");
      clearLevel("colour");
      clearLevel("size");
      if (selects.product.value) {
        beginChoiceLoad("brand");
      } else {
        latestBillingRequest += 1;
        hideVariant();
        status.textContent = "Choose a Product to begin.";
      }
    });

    selects.brand.addEventListener("change", () => {
      clearLevel("article");
      clearLevel("colour");
      clearLevel("size");
      if (!selects.brand.value) {
        latestBillingRequest += 1;
        hideVariant();
        return;
      }
      beginChoiceLoad(classification() === "article_colour" ? "article" : "colour");
    });

    selects.article.addEventListener("change", () => {
      clearLevel("colour");
      clearLevel("size");
      if (selects.article.value) {
        beginChoiceLoad("colour");
      } else {
        latestBillingRequest += 1;
        hideVariant();
      }
    });

    selects.colour.addEventListener("change", () => {
      clearLevel("size");
      if (classification() === "colour_size" && selects.colour.value) {
        beginChoiceLoad("size");
      } else {
        latestBillingRequest += 1;
        hideVariant();
        loadVariant(latestBillingRequest);
      }
    });

    selects.size.addEventListener("change", () => {
      latestBillingRequest += 1;
      hideVariant();
      loadVariant(latestBillingRequest);
    });

    lineQuantity.addEventListener("input", () => {
      addProductButton.disabled = false;
      updateNegativeWarning();
    });
    discountInput.addEventListener("input", updateTotals);
    paidInput.addEventListener("input", () => {
      paidWasEdited = true;
      paidWasEditedInput.value = "true";
      paidInput.dataset.paidSupplied = "true";
      updateTotals();
    });

    function addProductLine() {
      if (!currentVariant) {
        return;
      }
      const quantity = parseQuantity(lineQuantity.value, currentVariant.unit);
      const price = parseMoney(linePrice.value);
      if (quantity === null) {
        lineQuantity.setCustomValidity(
          currentVariant.unit === "metre"
            ? "Enter a positive metre quantity with up to three decimal places."
            : "Enter a positive whole-number quantity.",
        );
        lineQuantity.reportValidity();
        lineQuantity.setCustomValidity("");
        return;
      }
      if (price === null || price > 1000000000n) {
        linePrice.setCustomValidity("Enter a valid PKR selling price with up to two decimal places.");
        linePrice.reportValidity();
        linePrice.setCustomValidity("");
        return;
      }
      const items = draftItems();
      if (billLines.querySelectorAll("[data-bill-line]").length >= 100) {
        variantError.textContent = "A bill can contain no more than 100 items.";
        variantError.hidden = false;
        return;
      }
      const priorDraftQuantity = existingDraftQuantity(currentVariant.id);
      const projected = BigInt(currentVariant.current_balance) - priorDraftQuantity - quantity;
      const item = {
        variant_id: String(currentVariant.id),
        quantity: formatQuantity(quantity),
        unit_price: Number(price),
      };
      items.push(item);
      billItemsInput.value = JSON.stringify(items);
      const lineTotal = (quantity * price + 500n) / 1000n;
      appendBillRow(item, lineTotal, projected);
      const totalLines = billLines.querySelectorAll("[data-bill-line]").length;
      lineCount.textContent = `${totalLines} item${totalLines === 1 ? "" : "s"}`;
      lineQuantity.value = "";
      addProductButton.disabled = true;
      negativeWarning.hidden = true;
      updateTotals();
      updateCurrentBillSummary();
      refreshClothOptions(false);
      showProductConfirmation({ ...currentVariant, quantity: item.quantity });
    }

    addProductButton.addEventListener("click", addProductLine);

    const tailoringSection = billingForm.querySelector("[data-tailoring-addition]");
    tailoringSection.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target.matches("input, select")) {
        event.preventDefault();
      }
    });

    billingForm.addEventListener("submit", (event) => {
      actionInput.value = event.submitter
        ? event.submitter.dataset.billingAction || ""
        : "";
      if (billingForm.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }
      if (actionInput.value) {
        billingForm.dataset.submitting = "true";
      }
    });

    fallback.hidden = true;
    if (variantPanel.dataset.variantReady === "true") {
      currentVariant = {
        id: variantPanel.dataset.variantId,
        product: variantPanel.dataset.product,
        description: variantDescription.textContent.trim(),
        is_fabric: variantPanel.dataset.isFabric === "true",
        unit: variantPanel.dataset.unit,
        current_balance: variantPanel.dataset.currentBalance,
        default_selling_price: variantPanel.dataset.defaultPrice
          ? Number(variantPanel.dataset.defaultPrice)
          : null,
      };
    }
    applySaleMode();
    updateTotals();
    updateCurrentBillSummary();
    updateNegativeWarning();

    const tailoringRefresh = billingForm.querySelector("[data-tailoring-refresh]");
    const tailoringFallback = billingForm.querySelector("[data-tailoring-fallback]");
    if (tailoringRefresh && tailoringFallback) {
      const refreshButton = tailoringFallback.querySelector('button[value="open_tailoring"]');
      const customDescription = billingForm.querySelector("[data-tailoring-custom-description]");
      tailoringFallback.hidden = true;
      tailoringRefresh.addEventListener("change", () => billingForm.requestSubmit(refreshButton));
      if (customDescription) {
        customDescription.addEventListener("change", () => billingForm.requestSubmit(refreshButton));
      }
    }
    refreshClothOptions(true);
  }

  const measurementCategoryForm = document.querySelector("[data-measurement-category-form]");
  if (measurementCategoryForm) {
    const selector = measurementCategoryForm.querySelector("[data-measurement-category]");
    const fallback = measurementCategoryForm.querySelector("[data-measurement-category-fallback]");
    if (selector && fallback) {
      fallback.hidden = true;
      selector.addEventListener("change", () => measurementCategoryForm.submit());
    }
  }

  const customMeasurements = document.querySelector("[data-custom-measurements]");
  const addCustomMeasurement = document.querySelector("[data-add-custom-measurement]");
  if (customMeasurements && addCustomMeasurement) {
    function updateCustomRows() {
      const rows = Array.from(customMeasurements.querySelectorAll("[data-custom-measurement-row]"));
      rows.forEach((row, index) => {
        const name = row.querySelector('input[name="custom_name"]');
        const value = row.querySelector('input[name="custom_value"]');
        const remove = row.querySelector("[data-remove-custom-measurement]");
        name.id = `custom-name-${index}`;
        value.id = `custom-value-${index}`;
        row.querySelector(`label[for^="custom-name-"]`).htmlFor = name.id;
        row.querySelector(`label[for^="custom-value-"]`).htmlFor = value.id;
        remove.disabled = rows.length === 1;
      });
      addCustomMeasurement.disabled = rows.length >= 10;
    }

    function newCustomRow() {
      const row = document.createElement("div");
      row.className = "custom-measurement-row";
      row.dataset.customMeasurementRow = "";
      row.innerHTML = '<div class="field"><label for="custom-name-new">Measurement name</label><input id="custom-name-new" name="custom_name" maxlength="80" required></div><div class="field"><label for="custom-value-new">Value (inches)</label><input id="custom-value-new" name="custom_value" type="number" min="0.001" max="10000" step="0.001" inputmode="decimal" required></div><button type="button" class="secondary small" data-remove-custom-measurement>Remove</button>';
      return row;
    }

    addCustomMeasurement.addEventListener("click", () => {
      if (customMeasurements.querySelectorAll("[data-custom-measurement-row]").length >= 10) {
        return;
      }
      const row = newCustomRow();
      customMeasurements.append(row);
      updateCustomRows();
      row.querySelector('input[name="custom_name"]').focus();
    });
    customMeasurements.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove-custom-measurement]");
      if (!remove || customMeasurements.querySelectorAll("[data-custom-measurement-row]").length <= 1) {
        return;
      }
      remove.closest("[data-custom-measurement-row]").remove();
      updateCustomRows();
    });
    updateCustomRows();
  }

  const printReceipt = document.querySelector("[data-print-receipt]");
  if (printReceipt) {
    printReceipt.addEventListener("click", () => window.print());
  }

  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  const sidebar = document.querySelector("[data-sidebar]");
  if (sidebarToggle && sidebar) {
    const setSidebarOpen = (open) => {
      document.body.classList.toggle("sidebar-open", open);
      sidebarToggle.setAttribute("aria-expanded", String(open));
    };

    sidebarToggle.addEventListener("click", () => {
      setSidebarOpen(!document.body.classList.contains("sidebar-open"));
    });
    sidebar.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => setSidebarOpen(false));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        setSidebarOpen(false);
      }
    });
  }

  document.querySelectorAll("[data-delete-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const action = form.querySelector("[data-delete-action]");
      if (!action || action.value !== "request_delete") {
        return;
      }
      const label = form.dataset.deleteLabel || "this catalogue record";
      if (!window.confirm(`Permanently delete “${label}”? This is allowed only when it has no children and has never been used.`)) {
        event.preventDefault();
        return;
      }
      action.value = "delete_label";
      const confirmation = document.createElement("input");
      confirmation.type = "hidden";
      confirmation.name = "confirm_delete";
      confirmation.value = "yes";
      form.appendChild(confirmation);
    });
  });

  if (window.location.hash) {
    let targetId = window.location.hash.slice(1);
    try {
      targetId = decodeURIComponent(targetId);
    } catch (_error) {
      // A malformed fragment must not prevent the stock filters from working.
    }
    const target = document.getElementById(targetId);
    if (target) {
      window.requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
    }
  }
})();
