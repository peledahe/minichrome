// budget.js - Lógica y UI para el módulo de Presupuesto Categorizado (Ingresos, Gastos y Monedas)

const DEFAULT_CATEGORIES = {
    income: ['Salario', 'Freelance', 'Inversiones', 'Otros'],
    expense: ['Alimentación', 'Vivienda', 'Transporte', 'Servicios', 'Entretenimiento', 'Deudas', 'Ahorros', 'Otros']
};

let BUDGET_CATEGORIES = {
    income: [...DEFAULT_CATEGORIES.income],
    expense: [...DEFAULT_CATEGORIES.expense]
};

const budgetState = {
    income: [],
    expense: [],
    limits: {}, // Límites de gasto mensual por categoría
    incomeTargets: {}, // Metas de ingresos mensuales por categoría
    debtAllocation: 0, // Monto asignado a deudas
    selectedMonth: new Date().getMonth(), // 0-11
    selectedYear: new Date().getFullYear()
};

const currencyState = {
    symbol: 'Q',
    code: 'GTQ',
    secondEnabled: false,
    secondSymbol: 'US$',
    secondCode: 'USD',
    exchangeRate: 7.8
};

function fmtNum(n) {
    return Number(n || 0).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// Formateador de monedas inteligente (con separador de miles)
function formatMoney(amount, recordCurrency = 'local') {
    const amt = Number(amount || 0);
    if (!currencyState.secondEnabled) {
        return `${currencyState.symbol} ${fmtNum(amt)}`;
    }
    
    const isSecond = recordCurrency === 'second' || recordCurrency === 'USD' || recordCurrency === '$' || recordCurrency === currencyState.secondSymbol || recordCurrency === currencyState.secondCode;
    
    if (isSecond) {
        const localVal = amt * currencyState.exchangeRate;
        return `${currencyState.secondSymbol} ${fmtNum(amt)} <span class="budget-conv-label">(${currencyState.symbol} ${fmtNum(localVal)})</span>`;
    } else {
        const converted = amt / currencyState.exchangeRate;
        return `${currencyState.symbol} ${fmtNum(amt)} <span class="budget-conv-label">(${currencyState.secondSymbol} ${fmtNum(converted)})</span>`;
    }
}

// Cargar configuraciones de monedas
async function loadBudgetCurrencyConfig() {
    return new Promise((resolve) => {
        if (typeof chrome !== 'undefined' && chrome.storage) {
            chrome.storage.local.get([
                'budget_currency_symbol',
                'budget_currency_code',
                'budget_second_currency_enabled',
                'budget_second_currency_symbol',
                'budget_second_currency_code',
                'budget_exchange_rate'
            ], (result) => {
                if (result.budget_currency_symbol) currencyState.symbol = result.budget_currency_symbol;
                if (result.budget_currency_code) currencyState.code = result.budget_currency_code;
                if (result.budget_second_currency_enabled !== undefined) currencyState.secondEnabled = result.budget_second_currency_enabled;
                if (result.budget_second_currency_symbol) currencyState.secondSymbol = result.budget_second_currency_symbol;
                if (result.budget_second_currency_code) currencyState.secondCode = result.budget_second_currency_code;
                if (result.budget_exchange_rate) currencyState.exchangeRate = Number(result.budget_exchange_rate) || 7.8;

                populateCurrencySelectOptions();
                resolve();
            });
        } else {
            resolve();
        }
    });
}

// Poblar los desplegables de monedas dinámicamente según la configuración
function populateCurrencySelectOptions() {
    const shopCur = document.getElementById('shop-currency-select');
    const incomeCur = document.getElementById('income-currency-select');
    const editCur = document.getElementById('edit-currency');

    const optionsHtml = `
        <option value="local">${currencyState.code} (${currencyState.symbol})</option>
        ${currencyState.secondEnabled ? `<option value="second">${currencyState.secondCode} (${currencyState.secondSymbol})</option>` : ''}
    `;

    if (shopCur) shopCur.innerHTML = optionsHtml;
    if (incomeCur) incomeCur.innerHTML = optionsHtml;
    if (editCur) editCur.innerHTML = optionsHtml;

    // Actualizar símbolo de deudas en la cabecera
    const debtSymbolEl = document.getElementById('budget-debt-allocation-symbol');
    if (debtSymbolEl) debtSymbolEl.innerText = currencyState.symbol;
}

// Guardar la configuración de monedas en el storage
async function saveBudgetCurrencyConfig() {
    const symbol = (document.getElementById('cfg-currency-symbol')?.value || 'Q').trim();
    const code = (document.getElementById('cfg-currency-code')?.value || 'GTQ').trim().toUpperCase();
    const secondEnabled = document.getElementById('cfg-second-currency-enabled')?.checked || false;
    const secondSymbol = (document.getElementById('cfg-second-currency-symbol')?.value || 'US$').trim();
    const secondCode = (document.getElementById('cfg-second-currency-code')?.value || 'USD').trim().toUpperCase();
    const exchangeRate = parseFloat(document.getElementById('cfg-exchange-rate')?.value || '7.8');

    if (!symbol || !code || (secondEnabled && (Number.isNaN(exchangeRate) || exchangeRate <= 0))) {
        window.showToast('Valores de configuración de monedas inválidos', 'error');
        return false;
    }

    currencyState.symbol = symbol;
    currencyState.code = code;
    currencyState.secondEnabled = secondEnabled;
    currencyState.secondSymbol = secondSymbol;
    currencyState.secondCode = secondCode;
    currencyState.exchangeRate = exchangeRate;

    if (typeof chrome !== 'undefined' && chrome.storage) {
        await new Promise(resolve => {
            chrome.storage.local.set({
                'budget_currency_symbol': symbol,
                'budget_currency_code': code,
                'budget_second_currency_enabled': secondEnabled,
                'budget_second_currency_symbol': secondSymbol,
                'budget_second_currency_code': secondCode,
                'budget_exchange_rate': exchangeRate
            }, resolve);
        });
    }

    populateCurrencySelectOptions();
    return true;
}

// Cargar categorías dinámicas desde el almacenamiento
async function loadBudgetCategories() {
    return new Promise((resolve) => {
        if (typeof chrome !== 'undefined' && chrome.storage) {
            chrome.storage.local.get(['budget_categories'], (result) => {
                if (result.budget_categories) {
                    try {
                        const parsed = JSON.parse(result.budget_categories);
                        if (parsed.income && parsed.expense) {
                            BUDGET_CATEGORIES.income = Array.from(new Set([...DEFAULT_CATEGORIES.income, ...parsed.income]));
                            BUDGET_CATEGORIES.expense = Array.from(new Set([...DEFAULT_CATEGORIES.expense, ...parsed.expense]));
                        }
                    } catch (e) {
                        console.error('Error parsing budget categories:', e);
                    }
                }
                populateCategorySelects();
                resolve();
            });
        } else {
            resolve();
        }
    });
}

// Agregar una nueva categoría
async function addNewCategory(type, name) {
    name = (name || '').trim();
    if (!name) return;

    const capitalized = name.charAt(0).toUpperCase() + name.slice(1);

    if (BUDGET_CATEGORIES[type].includes(capitalized)) {
        window.showToast('Esta categoría ya existe.', 'info');
        return;
    }

    BUDGET_CATEGORIES[type].push(capitalized);

    if (typeof chrome !== 'undefined' && chrome.storage) {
        chrome.storage.local.get(['budget_categories'], async (result) => {
            let saved = { income: [], expense: [] };
            if (result.budget_categories) {
                try {
                    saved = JSON.parse(result.budget_categories);
                } catch (_) {}
            }
            if (!saved.income) saved.income = [];
            if (!saved.expense) saved.expense = [];

            if (!saved[type].includes(capitalized)) {
                saved[type].push(capitalized);
            }

            await new Promise(r => chrome.storage.local.set({ budget_categories: JSON.stringify(saved) }, r));
            window.showToast(`Categoría "${capitalized}" creada exitosamente`, 'success');
            
            populateCategorySelects();
            openBudgetLimitsModal(); 
            renderBudgetDashboard();
        });
    }
}

// Renombrar categoría dinámicamente con migración histórica en almacenamiento
async function renameCategory(type, catOld, catNew) {
    catNew = (catNew || '').trim();
    if (!catNew || catOld === catNew) return;

    const capitalized = catNew.charAt(0).toUpperCase() + catNew.slice(1);

    if (BUDGET_CATEGORIES[type].includes(capitalized)) {
        window.showToast('Esta categoría ya existe.', 'info');
        return;
    }

    // Actualizar array de categorías en memoria
    const idx = BUDGET_CATEGORIES[type].indexOf(catOld);
    if (idx !== -1) {
        BUDGET_CATEGORIES[type][idx] = capitalized;
    }

    // Migrar metas y presupuestos asociados
    if (type === 'expense') {
        if (budgetState.limits[catOld] !== undefined) {
            budgetState.limits[capitalized] = budgetState.limits[catOld];
            delete budgetState.limits[catOld];
        }
    } else {
        if (budgetState.incomeTargets[catOld] !== undefined) {
            budgetState.incomeTargets[capitalized] = budgetState.incomeTargets[catOld];
            delete budgetState.incomeTargets[catOld];
        }
    }

    // Guardar categorías y configuraciones de límites
    if (typeof chrome !== 'undefined' && chrome.storage) {
        const savedCategories = {
            income: BUDGET_CATEGORIES.income.filter(c => !DEFAULT_CATEGORIES.income.includes(c)),
            expense: BUDGET_CATEGORIES.expense.filter(c => !DEFAULT_CATEGORIES.expense.includes(c))
        };
        await new Promise(r => chrome.storage.local.set({ budget_categories: JSON.stringify(savedCategories) }, r));
        await Promise.all([
            py.set_config('budget_limits', JSON.stringify(budgetState.limits)),
            py.set_config('budget_income_targets', JSON.stringify(budgetState.incomeTargets))
        ]);
    }

    // Migración histórica de registros en storage_bridge
    const storageKey = type === 'expense' ? 'shopping' : 'income';
    if (typeof chrome !== 'undefined' && chrome.storage) {
        await new Promise((resolve) => {
            chrome.storage.local.get([storageKey], (res) => {
                const list = res[storageKey] || [];
                let updated = false;
                list.forEach(item => {
                    if (item.category === catOld) {
                        item.category = capitalized;
                        updated = true;
                    }
                });
                if (updated) {
                    chrome.storage.local.set({ [storageKey]: list }, resolve);
                } else {
                    resolve();
                }
            });
        });
    }

    window.showToast(`Categoría renombrada a "${capitalized}"`, 'success');
    await fetchBudget();
    openBudgetLimitsModal();
}

// Eliminar categoría dinámicamente con modal personalizado
let categoryToDelete = null;
let categoryDeleteType = null;

function requestDeleteCategory(type, catName) {
    // Si es categoría por defecto, no permitir borrar
    if (DEFAULT_CATEGORIES[type].includes(catName)) {
        window.showToast('No se pueden eliminar las categorías por defecto de la aplicación', 'info');
        return;
    }

    categoryToDelete = catName;
    categoryDeleteType = type;

    const modal = document.getElementById('confirm-delete-cat-modal');
    const text = document.getElementById('confirm-delete-cat-text');
    if (modal && text) {
        text.innerText = `¿Estás seguro de que deseas eliminar la categoría "${catName}"? Los registros pasados de esta categoría se reasignarán automáticamente a la categoría "Otros".`;
        modal.classList.add('active');
    }
}

async function confirmDeleteCategory() {
    if (!categoryToDelete || !categoryDeleteType) return;

    const type = categoryDeleteType;
    const catName = categoryToDelete;

    // Remover del listado global
    BUDGET_CATEGORIES[type] = BUDGET_CATEGORIES[type].filter(c => c !== catName);

    // Limpiar límites o estimados
    if (type === 'expense') {
        delete budgetState.limits[catName];
    } else {
        delete budgetState.incomeTargets[catName];
    }

    // Persistir categorías y límites
    if (typeof chrome !== 'undefined' && chrome.storage) {
        const savedCategories = {
            income: BUDGET_CATEGORIES.income.filter(c => !DEFAULT_CATEGORIES.income.includes(c)),
            expense: BUDGET_CATEGORIES.expense.filter(c => !DEFAULT_CATEGORIES.expense.includes(c))
        };
        await new Promise(r => chrome.storage.local.set({ budget_categories: JSON.stringify(savedCategories) }, r));
        await Promise.all([
            py.set_config('budget_limits', JSON.stringify(budgetState.limits)),
            py.set_config('budget_income_targets', JSON.stringify(budgetState.incomeTargets))
        ]);
    }

    // Reasignación histórica de registros a "Otros"
    const storageKey = type === 'expense' ? 'shopping' : 'income';
    if (typeof chrome !== 'undefined' && chrome.storage) {
        await new Promise((resolve) => {
            chrome.storage.local.get([storageKey], (res) => {
                const list = res[storageKey] || [];
                let updated = false;
                list.forEach(item => {
                    if (item.category === catName) {
                        item.category = 'Otros';
                        updated = true;
                    }
                });
                if (updated) {
                    chrome.storage.local.set({ [storageKey]: list }, resolve);
                } else {
                    resolve();
                }
            });
        });
    }

    document.getElementById('confirm-delete-cat-modal')?.classList.remove('active');
    window.showToast(`Categoría "${catName}" eliminada exitosamente`, 'success');
    categoryToDelete = null;
    categoryDeleteType = null;

    await fetchBudget();
    openBudgetLimitsModal();
}

// Poblar los desplegables de las modales de creación
function populateCategorySelects() {
    const shopSelect = document.getElementById('shop-category-select');
    if (shopSelect) {
        shopSelect.innerHTML = BUDGET_CATEGORIES.expense.map(cat => 
            `<option value="${cat}" ${cat === 'Otros' ? 'selected' : ''}>${cat}</option>`
        ).join('');
    }

    const incomeSelect = document.getElementById('income-category-select');
    if (incomeSelect) {
        incomeSelect.innerHTML = BUDGET_CATEGORIES.income.map(cat => 
            `<option value="${cat}" ${cat === 'Otros' ? 'selected' : ''}>${cat}</option>`
        ).join('');
    }
}

// Cargar datos de presupuesto
// Poblar los selects de mes y año del filtro de presupuesto
function initBudgetMonthFilter() {
    const monthSel = document.getElementById('budget-month-select');
    const yearSel = document.getElementById('budget-year-select');
    if (!monthSel || !yearSel) return;

    const months = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    monthSel.innerHTML = months.map((m, i) =>
        `<option value="${i}" ${i === budgetState.selectedMonth ? 'selected' : ''}>${m}</option>`
    ).join('');

    const currentYear = new Date().getFullYear();
    yearSel.innerHTML = '';
    for (let y = currentYear; y >= currentYear - 2; y--) {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        if (y === budgetState.selectedYear) opt.selected = true;
        yearSel.appendChild(opt);
    }

    monthSel.addEventListener('change', () => {
        budgetState.selectedMonth = Number(monthSel.value);
        fetchBudget();
    });
    yearSel.addEventListener('change', () => {
        budgetState.selectedYear = Number(yearSel.value);
        fetchBudget();
    });
}

// Eliminar del storage income y shopping con año anterior al año actual
async function purgeOldBudgetData() {
    try {
        if (!py) return;
        const currentYear = new Date().getFullYear();

        const allIncome = await py.get_income();
        const cleanIncome = allIncome.filter(i => {
            const y = parseInt((i.dueDate || '').substring(0, 4));
            return isNaN(y) || y >= currentYear;
        });
        if (cleanIncome.length !== allIncome.length) {
            // Guardar directamente en storage (acceso interno)
            const removed = allIncome.length - cleanIncome.length;
            // Borrar uno a uno usando delete_income para respetar el bridge
            const toDeleteIncome = allIncome.filter(i => {
                const y = parseInt((i.dueDate || '').substring(0, 4));
                return !isNaN(y) && y < currentYear;
            });
            for (const item of toDeleteIncome) {
                await py.delete_income(item.id);
            }
            console.log(`[Budget] Purga: ${removed} ingreso(s) de años anteriores eliminados.`);
        }

        const allExpense = await py.get_shopping();
        const cleanExpense = allExpense.filter(e => {
            const y = parseInt((e.dueDate || '').substring(0, 4));
            return isNaN(y) || y >= currentYear;
        });
        if (cleanExpense.length !== allExpense.length) {
            const removed = allExpense.length - cleanExpense.length;
            const toDeleteExpense = allExpense.filter(e => {
                const y = parseInt((e.dueDate || '').substring(0, 4));
                return !isNaN(y) && y < currentYear;
            });
            for (const item of toDeleteExpense) {
                await py.delete_shopping(item.id);
            }
            console.log(`[Budget] Purga: ${removed} gasto(s) de años anteriores eliminados.`);
        }
    } catch (err) {
        console.warn('[Budget] Error en purga de datos antiguos:', err);
    }
}

async function fetchBudget() {
    try {
        if (!py) return;

        // Primero cargar monedas y categorías
        await loadBudgetCurrencyConfig();
        await loadBudgetCategories();

        // Cargar ingresos, gastos, límites y metas de ingresos
        const [incomeData, expenseData, limitsRaw, targetsRaw, debtAllocRaw] = await Promise.all([
            py.get_income(),
            py.get_shopping(),
            py.get_config('budget_limits'),
            py.get_config('budget_income_targets'),
            py.get_debts_budget()
        ]);

        // Filtrar al mes/año seleccionado
        const monthStr = String(budgetState.selectedMonth + 1).padStart(2, '0');
        const prefix = `${budgetState.selectedYear}-${monthStr}`;
        budgetState.income = (incomeData || []).filter(i => (i.dueDate || '').startsWith(prefix));
        budgetState.expense = (expenseData || []).filter(e => (e.dueDate || '').startsWith(prefix));

        // Cargar límites por defecto si no existen (Gastos)
        const defaultLimits = {};
        BUDGET_CATEGORIES.expense.forEach(cat => {
            defaultLimits[cat] = cat === 'Vivienda' ? 2000 : (cat === 'Alimentación' ? 1000 : 500);
        });
        budgetState.limits = parseJSON(limitsRaw, defaultLimits);

        // Cargar metas por defecto si no existen (Ingresos)
        const defaultTargets = {};
        BUDGET_CATEGORIES.income.forEach(cat => {
            defaultTargets[cat] = cat === 'Salario' ? 5000 : 1000;
        });
        budgetState.incomeTargets = parseJSON(targetsRaw, defaultTargets);

        budgetState.debtAllocation = Number(debtAllocRaw) || 0;
        budgetState.limits['Deudas'] = budgetState.debtAllocation;

        renderBudgetDashboard();
        renderBudgetTransactions();
    } catch (err) {
        console.error('Error fetching budget data:', err);
        const container = document.getElementById('view-budget');
        if (container) {
            container.innerHTML = '<div class="ag-empty">Error al cargar el presupuesto</div>';
        }
    }
}

// Renderizar el balance general y las barras de progreso de categorías
function renderBudgetDashboard() {
    // Calcular totales convertidos a moneda local
    let totalIncome = 0;
    budgetState.income.forEach(item => {
        const val = Number(item.value) || 0;
        const isSecond = item.currency === 'second' || item.currency === '$' || item.currency === currencyState.secondSymbol || item.currency === currencyState.secondCode;
        totalIncome += isSecond ? (val * currencyState.exchangeRate) : val;
    });

    let totalExpense = 0;
    budgetState.expense.forEach(item => {
        const val = Number(item.value) || 0;
        const isSecond = item.currency === 'second' || item.currency === '$' || item.currency === currencyState.secondSymbol || item.currency === currencyState.secondCode;
        totalExpense += isSecond ? (val * currencyState.exchangeRate) : val;
    });

    const balance = totalIncome - totalExpense;

    // Actualizar textos en la UI (con formateador dinámico)
    const incomeEl = document.getElementById('budget-total-income');
    if (incomeEl) incomeEl.innerHTML = formatMoney(totalIncome, 'local');

    const expenseEl = document.getElementById('budget-total-expense');
    if (expenseEl) expenseEl.innerHTML = formatMoney(totalExpense, 'local');
    
    const balanceEl = document.getElementById('budget-total-balance');
    const balanceCard = document.getElementById('budget-balance-card-main');
    const balanceIcon = document.getElementById('budget-balance-icon-main');
    if (balanceEl) {
        balanceEl.innerHTML = formatMoney(balance, 'local');
        balanceEl.className = 'shop-total-combined ' + (balance >= 0 ? 'positive' : 'negative');
    }
    if (balanceCard && balanceIcon) {
        if (balance >= 0) {
            balanceCard.style.background = 'rgba(46, 213, 115, 0.03)';
            balanceCard.style.borderColor = 'rgba(46, 213, 115, 0.12)';
            balanceIcon.innerText = '⚖️';
            balanceIcon.style.background = 'rgba(46, 213, 115, 0.1)';
        } else {
            balanceCard.style.background = 'rgba(255, 118, 117, 0.03)';
            balanceCard.style.borderColor = 'rgba(255, 118, 117, 0.12)';
            balanceIcon.innerText = '⚠️';
            balanceIcon.style.background = 'rgba(255, 118, 117, 0.1)';
        }
    }

    // Input de asignación a deudas
    const debtInput = document.getElementById('budget-debt-allocation');
    if (debtInput) {
        debtInput.value = budgetState.debtAllocation;
    }

    // Calcular gastos por categoría en moneda local — separando confirmed y projected
    const expenseByCat = {};
    const expenseByCatProjected = {};
    BUDGET_CATEGORIES.expense.forEach(cat => {
        expenseByCat[cat] = 0;
        expenseByCatProjected[cat] = 0;
    });

    budgetState.expense.forEach(item => {
        const cat = item.category || 'Otros';
        const val = Number(item.value) || 0;
        const isSecond = item.currency === 'second' || item.currency === '$' || item.currency === currencyState.secondSymbol || item.currency === currencyState.secondCode;
        const valLocal = isSecond ? (val * currencyState.exchangeRate) : val;
        const isConfirmed = item.status === 'confirmed';

        const target = isConfirmed ? expenseByCat : expenseByCatProjected;
        if (target[cat] !== undefined) {
            target[cat] += valLocal;
        } else {
            if (target['Otros'] === undefined) target['Otros'] = 0;
            target['Otros'] += valLocal;
        }
    });

    // Renderizar barras de progreso dobles por categoría
    const progressContainer = document.getElementById('budget-category-progress');
    if (progressContainer) {
        progressContainer.innerHTML = BUDGET_CATEGORIES.expense.map(cat => {
            const confirmed = expenseByCat[cat] || 0;
            const projected = expenseByCatProjected[cat] || 0;
            const total = confirmed + projected;
            const limit = budgetState.limits[cat] || 0;
            const isOverLimit = limit > 0 && total > limit;
            const pctConfirmed = limit > 0 ? Math.min(100, (confirmed / limit) * 100) : 0;
            const pctProjected = limit > 0 ? Math.min(100 - pctConfirmed, (projected / limit) * 100) : 0;
            
            let barColor = '#6c5ce7'; 
            let txtColor = 'var(--ag-text)';
            if (isOverLimit) { barColor = '#ff7675'; txtColor = '#ff7675'; }
            else if ((pctConfirmed + pctProjected) >= 90) barColor = '#ff7675';
            else if ((pctConfirmed + pctProjected) >= 75) barColor = '#ffeaa7';

            const localSym = currencyState.symbol;
            return `
                <div class="budget-cat-progress-row" style="margin-bottom:12px; padding:4px; border-radius:6px; background:${isOverLimit ? 'rgba(255,118,117,0.04)' : 'transparent'};">
                    <div style="display:flex; justify-content:space-between; font-size:0.84rem; margin-bottom:4px;">
                        <span style="font-weight:600; color:${txtColor};">${cat} ${isOverLimit ? '⚠️' : ''}</span>
                        <span style="color:var(--ag-text-muted); font-size:0.78rem;">
                            <span style="color:var(--ag-text);">${localSym} ${fmtNum(confirmed)}</span>
                            ${projected > 0 ? `<span style="color:#a29bfe;"> +${localSym} ${fmtNum(projected)} proy.</span>` : ''}
                            / ${localSym} ${fmtNum(limit)}
                        </span>
                    </div>
                    <div style="background:rgba(255,255,255,0.06); height:8px; border-radius:99px; overflow:hidden; display:flex; border:1px solid rgba(255,255,255,0.04);">
                        <div style="width:${pctConfirmed}%; background:${barColor}; height:100%; border-radius:99px 0 0 99px; transition:width 0.4s ease;"></div>
                        <div style="width:${pctProjected}%; background:rgba(162,155,254,0.45); height:100%; background-image:repeating-linear-gradient(45deg,transparent,transparent 3px,rgba(255,255,255,0.08) 3px,rgba(255,255,255,0.08) 6px); transition:width 0.4s ease;"></div>
                    </div>
                    <div style="display:flex; gap:12px; margin-top:3px; font-size:0.72rem; color:var(--ag-text-muted);">
                        <span style="display:flex; align-items:center; gap:3px;"><span style="width:8px; height:8px; border-radius:50%; background:${barColor}; display:inline-block;"></span>Ejecutado</span>
                        ${projected > 0 ? `<span style="display:flex; align-items:center; gap:3px;"><span style="width:8px; height:8px; border-radius:50%; background:rgba(162,155,254,0.6); display:inline-block;"></span>Proyectado</span>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }
}

// Renderizar las tablas o listados de ingresos y gastos
function renderBudgetTransactions() {
    // Ingresos
    const incomeList = document.getElementById('budget-income-list');
    if (incomeList) {
        if (budgetState.income.length === 0) {
            incomeList.innerHTML = '<div class="ag-empty">No hay ingresos registrados</div>';
        } else {
            incomeList.innerHTML = budgetState.income.map(item => {
                const isSecond = item.currency === 'second' || item.currency === '$' || item.currency === currencyState.secondSymbol || item.currency === currencyState.secondCode;
                const formattedVal = formatMoney(item.value, isSecond ? 'second' : 'local');
                const isProjected = item.status !== 'confirmed';

                return `
                    <div class="ag-item budget-item ${isProjected ? 'budget-projected' : ''}" style="border-left: 3px ${isProjected ? 'dashed' : 'solid'} ${isProjected ? 'rgba(46,213,115,0.45)' : '#2ed573'}; margin-bottom: 6px; padding: 10px 14px; background: ${isProjected ? 'rgba(46,213,115,0.03)' : 'var(--ag-card-bg)'}; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; opacity:${isProjected ? '0.82' : '1'}">
                        <div>
                            <div style="font-weight: 600; font-size: 0.88rem; color: var(--ag-text); display:flex; align-items:center; gap:6px;">
                                ${escapeHtml(item.text)}
                                ${isProjected ? '<span class="budget-projected-badge">Proyectado</span>' : ''}
                            </div>
                            <div style="font-size: 0.76rem; color: var(--ag-text-muted); display: flex; gap: 8px;">
                                <span>🏷️ ${escapeHtml(item.category || 'Otros')}</span>
                                <span>📅 ${item.dueDate || 'Sin fecha'}</span>
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-weight: 700; color: ${isProjected ? 'rgba(46,213,115,0.6)' : '#2ed573'}; font-size: 0.9rem;">+ ${formattedVal}</span>
                            <div style="display: flex; gap: 4px; align-items:center;">
                                ${isProjected ? `<button class="ag-btn budget-confirm-btn" data-type="income" data-id="${item.id}" style="padding:4px 6px; font-size:0.8rem; background:rgba(46,213,115,0.15); border:1px solid rgba(46,213,115,0.4); color:#2ed573; cursor:pointer; border-radius:4px; line-height:1;" title="Confirmar ingreso">✓</button>` : ''}
                                <button class="ag-edit-btn" data-action="openEditModal" data-type="income" data-json='${jsonStr(item)}' style="background:none; border:none; cursor:pointer; font-size:0.85rem;">✏️</button>
                                <button class="ag-delete-btn" data-action="deleteIncome" data-id="${item.id}" style="background:none; border:none; cursor:pointer; font-size:0.85rem;">🗑️</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    // Gastos
    const expenseList = document.getElementById('budget-expense-list');
    if (expenseList) {
        if (budgetState.expense.length === 0) {
            expenseList.innerHTML = '<div class="ag-empty">No hay gastos registrados</div>';
        } else {
            expenseList.innerHTML = budgetState.expense.map(item => {
                const isSecond = item.currency === 'second' || item.currency === '$' || item.currency === currencyState.secondSymbol || item.currency === currencyState.secondCode;
                const formattedVal = formatMoney(item.value, isSecond ? 'second' : 'local');
                const isProjected = item.status !== 'confirmed';

                return `
                    <div class="ag-item budget-item ${isProjected ? 'budget-projected' : ''}" style="border-left: 3px ${isProjected ? 'dashed' : 'solid'} ${isProjected ? 'rgba(255,118,117,0.45)' : '#ff7675'}; margin-bottom: 6px; padding: 10px 14px; background: ${isProjected ? 'rgba(255,118,117,0.03)' : 'var(--ag-card-bg)'}; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; opacity:${isProjected ? '0.82' : '1'}">
                        <div>
                            <div style="font-weight: 600; font-size: 0.88rem; color: var(--ag-text); display:flex; align-items:center; gap:6px;">
                                ${escapeHtml(item.text)}
                                ${isProjected ? '<span class="budget-projected-badge">Proyectado</span>' : ''}
                            </div>
                            <div style="font-size: 0.76rem; color: var(--ag-text-muted); display: flex; gap: 8px;">
                                <span>🏷️ ${escapeHtml(item.category || 'Otros')}</span>
                                <span>📅 ${item.dueDate || 'Sin fecha'}</span>
                                ${item.paymentMethod ? `<span>💳 ${escapeHtml(item.paymentMethod)}</span>` : ''}
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-weight: 700; color: ${isProjected ? 'rgba(255,118,117,0.6)' : '#ff7675'}; font-size: 0.9rem;">- ${formattedVal}</span>
                            <div style="display: flex; gap: 4px; align-items:center;">
                                ${isProjected ? `<button class="ag-btn budget-confirm-btn" data-type="shopping" data-id="${item.id}" style="padding:4px 6px; font-size:0.8rem; background:rgba(255,118,117,0.15); border:1px solid rgba(255,118,117,0.4); color:#ff7675; cursor:pointer; border-radius:4px; line-height:1;" title="Confirmar gasto">✓</button>` : ''}
                                <button class="ag-edit-btn" data-action="openEditModal" data-type="shopping" data-json='${jsonStr(item)}' style="background:none; border:none; cursor:pointer; font-size:0.85rem;">✏️</button>
                                <button class="ag-delete-btn" data-action="deleteShopping" data-id="${item.id}" style="background:none; border:none; cursor:pointer; font-size:0.85rem;">🗑️</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }
}

// Actualizar asignación de deudas desde el input
async function updateDebtAllocation(val) {
    budgetState.debtAllocation = Number(val) || 0;
    budgetState.limits['Deudas'] = budgetState.debtAllocation;
    if (py) {
        await Promise.all([
            py.save_debts_budget(budgetState.debtAllocation),
            py.set_config('budget_limits', JSON.stringify(budgetState.limits))
        ]);
        if (window.fetchDebts) window.fetchDebts();
        renderBudgetDashboard();
    }
}

// Configurar modal de límites de presupuesto (con pestañas y edición de categorías)
function openBudgetLimitsModal() {
    const modal = document.getElementById('budget-limits-modal');
    if (!modal) return;

    // Cargar campos de configuración de moneda en los inputs
    const symbolInput = document.getElementById('cfg-currency-symbol');
    const codeInput = document.getElementById('cfg-currency-code');
    const secondEnabledInput = document.getElementById('cfg-second-currency-enabled');
    const secondSymbolInput = document.getElementById('cfg-second-currency-symbol');
    const secondCodeInput = document.getElementById('cfg-second-currency-code');
    const exchangeRateInput = document.getElementById('cfg-exchange-rate');

    if (symbolInput) symbolInput.value = currencyState.symbol;
    if (codeInput) codeInput.value = currencyState.code;
    if (secondEnabledInput) {
        secondEnabledInput.checked = currencyState.secondEnabled;
        const fields = document.getElementById('cfg-second-currency-fields');
        if (fields) fields.style.display = currencyState.secondEnabled ? 'block' : 'none';
    }
    if (secondSymbolInput) secondSymbolInput.value = currencyState.secondSymbol;
    if (secondCodeInput) secondCodeInput.value = currencyState.secondCode;
    if (exchangeRateInput) exchangeRateInput.value = currencyState.exchangeRate;

    // 1. Generar inputs dinámicamente con las categorías de gastos actuales
    const expenseContainer = modal.querySelector('.limits-inputs-list');
    if (expenseContainer) {
        expenseContainer.innerHTML = BUDGET_CATEGORIES.expense.map(cat => {
            const isDefault = DEFAULT_CATEGORIES.expense.includes(cat);
            return `
                <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 6px; flex: 1; overflow: hidden;">
                        <span id="cat-label-expense-${cat}" style="font-size: 0.9rem; color: var(--ag-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${cat}</span>
                        <div id="cat-edit-wrapper-expense-${cat}" style="display: none; flex: 1;">
                            <input type="text" id="cat-edit-input-expense-${cat}" class="ag-input" style="width: 100%; font-size: 0.8rem; padding: 2px 6px;" value="${cat}">
                        </div>
                        <button class="cat-action-btn edit-cat-btn" data-type="expense" data-cat="${cat}" style="background: none; border: none; cursor: pointer; padding: 2px; font-size: 0.85rem;" title="Editar nombre">✏️</button>
                        ${!isDefault ? `<button class="cat-action-btn delete-cat-btn" data-type="expense" data-cat="${cat}" style="background: none; border: none; cursor: pointer; padding: 2px; font-size: 0.85rem;" title="Eliminar categoría">🗑️</button>` : ''}
                    </div>
                    <input type="number" id="limit-input-${cat}" class="ag-input" style="width: 110px; text-align: right;" value="${budgetState.limits[cat] || 0}" step="0.01" min="0">
                </div>
            `;
        }).join('');
    }

    // 2. Generar inputs dinámicamente con las categorías de ingresos actuales
    const incomeContainer = modal.querySelector('.income-targets-inputs-list');
    if (incomeContainer) {
        incomeContainer.innerHTML = BUDGET_CATEGORIES.income.map(cat => {
            const isDefault = DEFAULT_CATEGORIES.income.includes(cat);
            return `
                <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 6px; flex: 1; overflow: hidden;">
                        <span id="cat-label-income-${cat}" style="font-size: 0.9rem; color: var(--ag-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${cat}</span>
                        <div id="cat-edit-wrapper-income-${cat}" style="display: none; flex: 1;">
                            <input type="text" id="cat-edit-input-income-${cat}" class="ag-input" style="width: 100%; font-size: 0.8rem; padding: 2px 6px;" value="${cat}">
                        </div>
                        <button class="cat-action-btn edit-cat-btn" data-type="income" data-cat="${cat}" style="background: none; border: none; cursor: pointer; padding: 2px; font-size: 0.85rem;" title="Editar nombre">✏️</button>
                        ${!isDefault ? `<button class="cat-action-btn delete-cat-btn" data-type="income" data-cat="${cat}" style="background: none; border: none; cursor: pointer; padding: 2px; font-size: 0.85rem;" title="Eliminar categoría">🗑️</button>` : ''}
                    </div>
                    <input type="number" id="target-input-${cat}" class="ag-input" style="width: 110px; text-align: right;" value="${budgetState.incomeTargets[cat] || 0}" step="0.01" min="0">
                </div>
            `;
        }).join('');
    }

    modal.classList.add('active');
}

// Guardar los límites, estimados y monedas editadas
async function saveBudgetLimits() {
    // 1. Guardar configuraciones de límites
    BUDGET_CATEGORIES.expense.forEach(cat => {
        const input = document.getElementById(`limit-input-${cat}`);
        if (input) {
            budgetState.limits[cat] = Number(input.value) || 0;
        }
    });

    BUDGET_CATEGORIES.income.forEach(cat => {
        const input = document.getElementById(`target-input-${cat}`);
        if (input) {
            budgetState.incomeTargets[cat] = Number(input.value) || 0;
        }
    });

    // 2. Guardar monedas
    const ok = await saveBudgetCurrencyConfig();
    if (!ok) return;

    // Sincronizar asignación de deudas si se editó desde el modal de límites
    if (budgetState.limits['Deudas'] !== undefined) {
        budgetState.debtAllocation = budgetState.limits['Deudas'];
        const debtInput = document.getElementById('budget-debt-allocation');
        if (debtInput) {
            debtInput.value = budgetState.debtAllocation;
        }
        if (window.fetchDebts) window.fetchDebts(); // Actualiza el modulo de deudas con el nuevo presupuesto
    }

    if (py) {
        await Promise.all([
            py.set_config('budget_limits', JSON.stringify(budgetState.limits)),
            py.set_config('budget_income_targets', JSON.stringify(budgetState.incomeTargets)),
            py.save_debts_budget(budgetState.debtAllocation)
        ]);
        window.showToast('Límites, estimados y monedas actualizados exitosamente', 'success');
        document.getElementById('budget-limits-modal')?.classList.remove('active');
        renderBudgetDashboard();
    }
}

// Exponer de forma global para edición dinámica de categorías en modal general
window.populateEditCategorySelect = function(type, selectedValue) {
    const select = document.getElementById('edit-category');
    if (!select) return;
    
    const categories = (type === 'shopping' || type === 'expense') ? BUDGET_CATEGORIES.expense : BUDGET_CATEGORIES.income;
    
    select.innerHTML = categories.map(cat => 
        `<option value="${cat}" ${cat === selectedValue ? 'selected' : ''}>${cat}</option>`
    ).join('');
};

// Colapsabilidad horizontal de columnas del presupuesto
function toggleBudgetColumn(colId) {
    const col = document.getElementById(colId);
    const btn = document.querySelector(`.col-toggle-btn[data-col="${colId}"]`);
    if (!col || !btn) return;

    const isVisible = !col.classList.contains('col-collapsed');
    
    if (isVisible) {
        col.classList.add('col-collapsed');
        btn.classList.remove('active');
    } else {
        col.classList.remove('col-collapsed');
        btn.classList.add('active');
    }
    
    updateBudgetGridTemplate();
}

function updateBudgetGridTemplate() {
    const grid = document.getElementById('budget-main-grid');
    if (!grid) return;

    const showIncome = !document.getElementById('col-income').classList.contains('col-collapsed');
    const showExpenses = !document.getElementById('col-expenses').classList.contains('col-collapsed');
    const showLimits = !document.getElementById('col-limits').classList.contains('col-collapsed');

    const cols = [];
    cols.push(showIncome ? '1fr' : '0px');
    cols.push(showExpenses ? '1.2fr' : '0px');
    cols.push(showLimits ? '1fr' : '0px');

    grid.style.gridTemplateColumns = cols.join(' ');
}

// Inicializar escuchas de eventos de la pestaña de presupuesto de forma programática y robusta (CSP y delegación)
function initBudgetListeners() {
    console.log("Budget dynamic listeners initialized");

    // Inicializar selector de mes/año y ejecutar purga de datos viejos
    initBudgetMonthFilter();
    purgeOldBudgetData();

    // Delegación de eventos click a nivel de document
    document.addEventListener('click', (e) => {
        // 1. Selector de visibilidad de columnas
        const colToggle = e.target.closest('.col-toggle-btn');
        if (colToggle) {
            const colId = colToggle.getAttribute('data-col');
            toggleBudgetColumn(colId);
            return;
        }

        // 2. Click en pestañas del modal de límites
        const modalTab = e.target.closest('#budget-limits-modal .modal-tab');
        if (modalTab) {
            document.querySelectorAll('#budget-limits-modal .modal-tab').forEach(t => {
                t.classList.remove('active');
                t.style.borderBottom = 'none';
                t.style.color = 'var(--ag-text-muted)';
            });
            document.querySelectorAll('#budget-limits-modal .modal-panel-content').forEach(p => {
                p.style.display = 'none';
            });

            modalTab.classList.add('active');
            const targetPanel = modalTab.getAttribute('data-panel');
            let color = 'var(--ag-text-muted)';
            if (targetPanel === 'panel-expense-limits') color = '#ff7675';
            else if (targetPanel === 'panel-income-targets') color = '#2ed573';
            else color = 'var(--ag-accent)';

            modalTab.style.borderBottom = `2px solid ${color}`;
            modalTab.style.color = color;

            const panel = document.getElementById(targetPanel);
            if (panel) panel.style.display = 'block';
            return;
        }

        // 3. Abrir modal de límites
        if (e.target.closest('#open-budget-limits-btn')) {
            openBudgetLimitsModal();
            return;
        }

        // 4. Cerrar modal de límites (X o Cancelar)
        if (e.target.closest('#close-budget-limits-x') || e.target.closest('#close-budget-limits-cancel')) {
            document.getElementById('budget-limits-modal')?.classList.remove('active');
            return;
        }

        // 5. Guardar límites
        if (e.target.closest('#save-budget-limits-btn')) {
            saveBudgetLimits();
            return;
        }

        // 6. Botón agregar nueva categoría
        if (e.target.closest('#add-new-cat-btn')) {
            const nameInput = document.getElementById('new-cat-name');
            const typeSelect = document.getElementById('new-cat-type');
            if (nameInput && typeSelect) {
                addNewCategory(typeSelect.value, nameInput.value);
                nameInput.value = '';
            }
            return;
        }

        // 7. Click en botón de edición de categoría en el modal
        const editCatBtn = e.target.closest('.edit-cat-btn');
        if (editCatBtn) {
            const type = editCatBtn.getAttribute('data-type');
            const cat = editCatBtn.getAttribute('data-cat');
            
            const labelEl = document.getElementById(`cat-label-${type}-${cat}`);
            const wrapperEl = document.getElementById(`cat-edit-wrapper-${type}-${cat}`);
            
            const isEditing = wrapperEl.style.display === 'block';
            if (!isEditing) {
                // Habilitar edición in-place
                labelEl.style.display = 'none';
                wrapperEl.style.display = 'block';
                editCatBtn.innerText = '✓';
                editCatBtn.title = 'Guardar';
                editCatBtn.style.color = '#2ed573';
            } else {
                // Confirmar y guardar la edición
                const inputEl = document.getElementById(`cat-edit-input-${type}-${cat}`);
                renameCategory(type, cat, inputEl.value);
            }
            return;
        }

        // 8. Click en botón de borrar categoría
        const deleteCatBtn = e.target.closest('.delete-cat-btn');
        if (deleteCatBtn) {
            const type = deleteCatBtn.getAttribute('data-type');
            const cat = deleteCatBtn.getAttribute('data-cat');
            
            const labelEl = document.getElementById(`cat-label-${type}-${cat}`);
            const wrapperEl = document.getElementById(`cat-edit-wrapper-${type}-${cat}`);
            const isEditing = wrapperEl && wrapperEl.style.display === 'block';

            if (isEditing) {
                // Si estaba editando, esto actúa como Cancelar
                labelEl.style.display = 'block';
                wrapperEl.style.display = 'none';
                const editBtn = document.querySelector(`.edit-cat-btn[data-type="${type}"][data-cat="${cat}"]`);
                if (editBtn) {
                    editBtn.innerText = '✏️';
                    editBtn.title = 'Editar nombre';
                    editBtn.style.color = '';
                }
            } else {
                // Solicitar confirmación de eliminación segura
                requestDeleteCategory(type, cat);
            }
            return;
        }

        // 9. Confirmar eliminación de categoría (modal personalizado)
        if (e.target.closest('#confirm-delete-cat-btn')) {
            confirmDeleteCategory();
            return;
        }

        // 10. Cancelar eliminación de categoría
        if (e.target.closest('#confirm-delete-cat-cancel')) {
            document.getElementById('confirm-delete-cat-modal')?.classList.remove('active');
            categoryToDelete = null;
            categoryDeleteType = null;
            return;
        }

        // 11. Confirmar un ingreso o gasto proyectado desde el listado
        const confirmBtn = e.target.closest('.budget-confirm-btn');
        if (confirmBtn) {
            const type = confirmBtn.getAttribute('data-type');
            const id = Number(confirmBtn.getAttribute('data-id'));
            confirmProjectedItem(type, id);
            return;
        }
    });

    // Eventos específicos (teclado / cambios de inputs) que no se pueden delegar por clicks
    document.addEventListener('keydown', (e) => {
        if (e.target && e.target.id === 'new-cat-name' && e.key === 'Enter') {
            e.preventDefault();
            const nameInput = document.getElementById('new-cat-name');
            const typeSelect = document.getElementById('new-cat-type');
            if (nameInput && typeSelect) {
                addNewCategory(typeSelect.value, nameInput.value);
                nameInput.value = '';
            }
        }
    });

    document.addEventListener('change', (e) => {
        if (e.target && e.target.id === 'budget-debt-allocation') {
            updateDebtAllocation(e.target.value);
        }
        
        // Interruptor de visibilidad para campos de moneda secundaria
        if (e.target && e.target.id === 'cfg-second-currency-enabled') {
            const fields = document.getElementById('cfg-second-currency-fields');
            if (fields) {
                fields.style.display = e.target.checked ? 'block' : 'none';
            }
        }
    });
}

// Confirmar un ítem proyectado cambiándolo a confirmed
async function confirmProjectedItem(type, id) {
    try {
        if (!py) return;
        if (type === 'shopping') {
            const list = await py.get_shopping();
            const item = list.find(x => x.id === id);
            if (item) {
                await py.update_shopping(id, item.text, item.value, item.currency, item.dueDate, item.paymentMethod, item.category, 'confirmed');
                window.showToast('Gasto confirmado y ejecutado', 'success');
            }
        } else if (type === 'income') {
            const list = await py.get_income();
            const item = list.find(x => x.id === id);
            if (item) {
                await py.update_income(id, item.text, item.value, item.currency, item.dueDate, item.category, 'confirmed');
                window.showToast('Ingreso confirmado y recibido', 'success');
            }
        }
        await fetchBudget();
    } catch (e) {
        console.error('Error confirming item:', e);
    }
}

// Ejecutar de inmediato o al cargar
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBudgetListeners);
} else {
    initBudgetListeners();
}

// Registrar funciones de presupuesto al ámbito de window
window.fetchBudget = fetchBudget;
window.updateDebtAllocation = updateDebtAllocation;
window.openBudgetLimitsModal = openBudgetLimitsModal;
window.saveBudgetLimits = saveBudgetLimits;
window.addNewCategory = addNewCategory;
window.toggleBudgetColumn = toggleBudgetColumn;
window.formatMoney = formatMoney;
window.currencyState = currencyState;
