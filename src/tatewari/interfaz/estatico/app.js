/* Tatewari — interfaz local.
 *
 * Sin dependencias: todo el DOM se construye con `h()`, nunca con innerHTML,
 * así que el texto de una nota o de un resumen no puede ejecutar nada.
 */
"use strict";

const S = {
  clave: "",
  estado: null,
  arbol: [],
  coleccion: "",
  nombreColeccion: "",
  elementos: [],
  seleccion: "",
  orden: { col: "titulo", asc: true },
  consulta: "",
  trabajos: [],
  vistos: new Set(),
  sondeo: null,
  pila: [],
  fichaActual: null,
};

const COLUMNAS = {
  rev: [
    ["titulo", "Título"], ["autores", "Autores"], ["anio", "Año"], ["revista", "Revista"], ["etiqueta", "Decisión"],
  ],
  vault: [
    ["titulo", "Nota"], ["autores", "Fuente"], ["anio", "Actualizada"], ["revista", "Tipo"], ["etiqueta", "Estado"],
  ],
};

const NOMBRE_ESTADO = {
  DRAFT: "Volver a DRAFT", REVIEW: "Pasar a REVIEW", APPROVED: "Aprobar", PUBLISHED: "Publicar",
};

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

function $(id) { return document.getElementById(id); }

function h(etiqueta, atributos, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(atributos || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "clase") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "datos") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

function svg(ruta, clase) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 16 16");
  s.setAttribute("aria-hidden", "true");
  if (clase) s.setAttribute("class", clase);
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", ruta);
  s.append(p);
  return s;
}
const FLECHA = "M3 5l5 6 5-6z";
const CARPETA = "M1.5 4h4.5l1.5 1.5h7V13h-13z";

function guardar(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ } }
function leer(clave, defecto) {
  try { const v = localStorage.getItem(clave); return v === null ? defecto : JSON.parse(v); } catch (e) { return defecto; }
}

async function api(ruta, opciones = {}) {
  const cabeceras = { "X-Tatewari-Clave": S.clave };
  let cuerpo = opciones.cuerpo;
  if (opciones.json !== undefined) {
    cabeceras["Content-Type"] = "application/json";
    cuerpo = JSON.stringify(opciones.json);
  }
  const r = await fetch(ruta, { method: cuerpo !== undefined ? "POST" : "GET", headers: cabeceras, body: cuerpo });
  let datos;
  try { datos = await r.json(); } catch (e) { datos = { error: "El servidor devolvió algo ilegible." }; }
  if (r.status === 401) sesionCaducada();
  if (!r.ok) throw new Error(datos.error || `Fallo ${r.status}`);
  return datos;
}

// Cada arranque de «tatewari interfaz» genera otra clave: una pestaña que
// quedó abierta de la vez anterior ya no sirve, y hay que decirlo en claro.
let _caducada = false;
function sesionCaducada() {
  if (_caducada) return;
  _caducada = true;
  clearTimeout(S.sondeo);
  $("lista-titulo").textContent = "Sesión cerrada";
  $("tabla-cabeza").replaceChildren();
  $("tabla-cuerpo").replaceChildren();
  $("lista-vacia").hidden = false;
  $("lista-vacia").replaceChildren(
    h("h2", {}, "Esta pestaña es de una sesión anterior"),
    h("p", {}, "Tatewari se reinició y usa una clave nueva. Cierra esta pestaña y abre la interfaz otra vez con «tatewari interfaz» o con el acceso directo."),
  );
  $("detalle").replaceChildren();
}
window.addEventListener("hashchange", () => { if (/t=/.test(location.hash)) location.reload(); });

function avisar(texto, error = false) {
  const aviso = h("div", { clase: "aviso" + (error ? " error" : ""), role: error ? "alert" : "status" }, texto);
  $("avisos").append(aviso);
  setTimeout(() => aviso.remove(), error ? 9000 : 4500);
}

function autor() { return leer("tatewari_autor", "") || (S.estado && S.estado.usuario) || ""; }

function abrirDialogo(id) {
  return new Promise((resolver) => {
    const dlg = $(id);
    const cerrar = () => { dlg.removeEventListener("close", cerrar); resolver(dlg.returnValue === "ok"); };
    dlg.returnValue = "";
    dlg.addEventListener("close", cerrar);
    dlg.showModal();
  });
}

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------

async function arrancar() {
  const m = location.hash.match(/t=([^&]+)/);
  if (m) {
    S.clave = decodeURIComponent(m[1]);
    try { sessionStorage.setItem("tatewari_clave", S.clave); } catch (e) { /* nada */ }
    history.replaceState(null, "", location.pathname);
  } else {
    try { S.clave = sessionStorage.getItem("tatewari_clave") || ""; } catch (e) { S.clave = ""; }
  }
  if (!S.clave) {
    $("lista-vacia").replaceChildren(
      h("h2", {}, "Falta la clave de la sesión"),
      h("p", {}, "Abre la interfaz desde la consola con «tatewari interfaz», o con el acceso directo del Escritorio."),
    );
    return;
  }
  try {
    await api("/api/sesion", { json: {} });
    S.estado = await api("/api/estado");
  } catch (e) {
    $("lista-vacia").replaceChildren(h("h2", {}, "No se pudo abrir la sesión"), h("p", {}, e.message));
    return;
  }
  prepararEventos();
  prepararSeparadores();
  await recargarArbol();
  const previa = leer("tatewari_coleccion", "");
  const existe = (id) => S.arbol.some((g) => (g.hijos || []).some((n) => n.id === id || (n.hijos || []).some((x) => x.id === id)));
  if (previa && existe(previa)) await elegirColeccion(previa);
  else mostrarBienvenida();
  consultarModelo();
  setInterval(consultarModelo, 30000);
  // Lo que ya había terminado antes de abrir la página no se anuncia.
  sondearTrabajos("primera");
}

function mostrarBienvenida() {
  $("lista-titulo").textContent = "Tatewari";
  $("lista-cuenta").textContent = "";
  $("tabla-cabeza").replaceChildren();
  $("tabla-cuerpo").replaceChildren();
  const hayVault = !!(S.estado && S.estado.vault);
  $("lista-vacia").hidden = false;
  const bienvenida = [
    h("h2", {}, hayVault ? "Elige una colección" : "Empieza por tu Vault"),
    h("p", {}, hayVault
      ? "A la izquierda están tus revisiones sistemáticas y tu Vault de Obsidian. Arrastra un PDF, un Word o un PowerPoint a la ventana para que Tatewari lo lea."
      : "Dile a Tatewari en qué carpeta está (o estará) tu Vault de Obsidian. Ahí escribirá las notas de tus documentos."),
  ];
  if (!hayVault) bienvenida.push(h("button", { type: "button", clase: "boton primario", onclick: configurarVault }, "Configurar Vault"));
  $("lista-vacia").replaceChildren(...bienvenida);
  $("detalle").replaceChildren();
  $("ruta-vault").textContent = S.estado && S.estado.vault ? S.estado.vault : "Sin Vault configurado";
}

// ---------------------------------------------------------------------------
// Árbol de colecciones
// ---------------------------------------------------------------------------

async function recargarArbol() {
  try {
    S.arbol = await api("/api/colecciones");
  } catch (e) {
    avisar(e.message, true);
    return;
  }
  const cerrados = new Set(leer("tatewari_cerrados", []));
  const raiz = $("arbol");
  raiz.replaceChildren();
  for (const grupo of S.arbol) {
    const lista = h("ul", { clase: "hijos", role: "group" });
    const cont = h("div", { clase: "grupo" + (cerrados.has(grupo.id) ? " cerrado" : "") },
      h("button", {
        type: "button", clase: "grupo-cabeza", "aria-expanded": String(!cerrados.has(grupo.id)),
        onclick: (ev) => alternar(grupo.id, cont, ev.currentTarget),
      }, svg(FLECHA, "flecha"), grupo.nombre),
      lista);
    if (grupo.sin_configurar) {
      lista.append(h("li", {}, h("button", { type: "button", clase: "boton chico configurar", onclick: configurarVault }, "Configurar Vault…")));
    }
    if (grupo.id === "revisiones" && !grupo.hijos.length) {
      lista.append(h("li", { clase: "tenue configurar" }, "Ninguna todavía"));
    }
    for (const nodo of grupo.hijos || []) lista.append(nodoArbol(nodo, 0, cerrados));
    raiz.append(cont);
  }
  marcarActiva();
  $("ruta-vault").textContent = S.estado && S.estado.vault ? S.estado.vault : "Sin Vault configurado";
}

function nodoArbol(nodo, nivel, cerrados) {
  const tieneHijos = (nodo.hijos || []).length > 0;
  const li = h("li", { clase: "nodo" + (cerrados.has(nodo.id) ? " cerrado" : "") });
  const fila = h("button", {
    type: "button", clase: "fila-arbol", datos: { id: nodo.id },
    onclick: () => elegirColeccion(nodo.id),
  });
  fila.style.setProperty("--nivel", nivel);
  if (tieneHijos) {
    const flecha = svg(FLECHA, "flecha");
    flecha.addEventListener("click", (ev) => { ev.stopPropagation(); alternar(nodo.id, li, fila); });
    fila.append(flecha, svg(CARPETA, "icono-carpeta"));
  } else {
    fila.append(h("span", { clase: "hueco-flecha" }), h("span", { clase: "punto m-" + (nodo.marca || "") }));
  }
  fila.append(h("span", { clase: "nombre" }, nodo.nombre));
  if (nodo.cuenta !== undefined) fila.append(h("span", { clase: "cuenta-nodo" }, nodo.cuenta));
  li.append(fila);
  if (tieneHijos) {
    const hijos = h("ul", { clase: "hijos" });
    for (const hijo of nodo.hijos) hijos.append(nodoArbol(hijo, nivel + 1, cerrados));
    li.append(hijos);
  }
  return li;
}

function alternar(id, contenedor, boton) {
  const cerrados = new Set(leer("tatewari_cerrados", []));
  const cerrar = !contenedor.classList.contains("cerrado");
  contenedor.classList.toggle("cerrado", cerrar);
  if (boton) boton.setAttribute("aria-expanded", String(!cerrar));
  if (cerrar) cerrados.add(id); else cerrados.delete(id);
  guardar("tatewari_cerrados", [...cerrados]);
}

function marcarActiva() {
  for (const fila of document.querySelectorAll(".fila-arbol")) {
    fila.classList.toggle("activa", fila.dataset.id === S.coleccion);
    if (fila.dataset.id === S.coleccion) S.nombreColeccion = fila.querySelector(".nombre").textContent;
  }
}

// ---------------------------------------------------------------------------
// Lista de elementos
// ---------------------------------------------------------------------------

async function elegirColeccion(id) {
  if (S.coleccion !== id) { S.seleccion = ""; S.pila = []; }
  S.coleccion = id;
  guardar("tatewari_coleccion", id);
  marcarActiva();
  await recargarElementos();
}

async function recargarElementos() {
  if (!S.coleccion) return;
  try {
    S.elementos = await api(`/api/elementos?coleccion=${encodeURIComponent(S.coleccion)}&q=${encodeURIComponent(S.consulta)}`);
  } catch (e) {
    avisar(e.message, true);
    S.elementos = [];
  }
  pintarLista();
  if (S.seleccion && S.elementos.some((x) => x.id === S.seleccion)) await mostrarFicha(S.seleccion);
  else { S.seleccion = ""; $("detalle").replaceChildren(fichaVacia()); }
}

function tipoColeccion() { return S.coleccion.startsWith("rev:") ? "rev" : "vault"; }

function pintarLista() {
  const columnas = COLUMNAS[tipoColeccion()];
  const titulo = S.coleccion.startsWith("rev:")
    ? `${S.coleccion.split(":")[1]} · ${S.nombreColeccion}`
    : S.nombreColeccion;
  $("lista-titulo").textContent = titulo;
  $("lista-cuenta").textContent = `${S.elementos.length} elemento${S.elementos.length === 1 ? "" : "s"}`;

  const cabeza = $("tabla-cabeza");
  cabeza.replaceChildren(...columnas.map(([clave, nombre]) =>
    h("th", {
      scope: "col", clase: "col-" + clave, tabindex: "0", "aria-sort": S.orden.col === clave ? (S.orden.asc ? "ascending" : "descending") : "none",
      onclick: () => ordenarPor(clave),
      onkeydown: (ev) => { if (ev.key === "Enter") ordenarPor(clave); },
    }, nombre, S.orden.col === clave ? h("span", { clase: "orden" }, S.orden.asc ? "▲" : "▼") : null)));

  const filas = [...S.elementos].sort((a, b) => {
    const x = String(a[S.orden.col] || ""), y = String(b[S.orden.col] || "");
    return (S.orden.asc ? 1 : -1) * x.localeCompare(y, "es", { numeric: true, sensitivity: "base" });
  });
  const cuerpo = $("tabla-cuerpo");
  cuerpo.replaceChildren(...filas.map((e) => {
    const tr = h("tr", {
      datos: { id: e.id }, clase: e.id === S.seleccion ? "sel" : null, "aria-selected": String(e.id === S.seleccion),
      onclick: () => seleccionar(e.id),
      ondblclick: () => abrirFuera(e),
    });
    for (const [clave] of columnas) {
      if (clave === "etiqueta") {
        tr.append(h("td", {}, e.etiqueta ? h("span", { clase: "chip m-" + e.marca }, e.etiqueta) : "",
          e.quien === "conflicto" ? " ⚠" : null));
      } else {
        tr.append(h("td", { title: e[clave] || "" }, e[clave] || ""));
      }
    }
    return tr;
  }));
  const vacio = $("lista-vacia");
  vacio.hidden = filas.length > 0;
  if (!filas.length) {
    vacio.replaceChildren(
      h("h2", {}, S.consulta ? "Nada coincide con la búsqueda" : "Colección vacía"),
      h("p", {}, S.consulta ? "Prueba con otras palabras." :
        tipoColeccion() === "vault" ? "Arrastra un documento a la ventana o pulsa «Añadir documento»." : "No hay registros con esa decisión."),
    );
  }
}

function ordenarPor(clave) {
  if (S.orden.col === clave) S.orden.asc = !S.orden.asc;
  else S.orden = { col: clave, asc: true };
  pintarLista();
}

async function seleccionar(id) {
  S.seleccion = id;
  S.pila = [];
  for (const tr of $("tabla-cuerpo").rows) {
    const sel = tr.dataset.id === id;
    tr.classList.toggle("sel", sel);
    tr.setAttribute("aria-selected", String(sel));
    if (sel) tr.scrollIntoView({ block: "nearest" });
  }
  await mostrarFicha(id);
}

function abrirFuera(e) {
  if (tipoColeccion() === "vault") {
    api(`/api/elemento?coleccion=${encodeURIComponent(S.coleccion)}&id=${encodeURIComponent(e.id)}`)
      .then((d) => { location.href = d.obsidian; }).catch((err) => avisar(err.message, true));
  }
}

// ---------------------------------------------------------------------------
// Ficha
// ---------------------------------------------------------------------------

function fichaVacia() {
  return h("div", { clase: "vacio" }, h("p", {}, S.elementos.length ? "Elige un elemento de la lista." : ""));
}

async function mostrarFicha(id) {
  let d;
  try {
    d = await api(`/api/elemento?coleccion=${encodeURIComponent(S.coleccion)}&id=${encodeURIComponent(id)}`);
  } catch (e) {
    $("detalle").replaceChildren(h("div", { clase: "caja aviso-caja rojo" }, e.message));
    return;
  }
  pintarFicha(d);
}

function pintarFicha(d) {
  // Se recuerda qué ficha se ve para poder volver tras seguir un [[enlace]].
  S.fichaActual = d;
  const ficha = d.clase === "registro" ? fichaRegistro(d) : fichaNota(d);
  if (S.pila.length) {
    ficha.prepend(h("button", { type: "button", clase: "boton chico volver", onclick: volver }, "← Volver"));
  }
  $("detalle").replaceChildren(ficha);
  $("detalle").scrollTop = 0;
}

function volver() {
  const previa = S.pila.pop();
  if (previa) pintarFicha(previa);
}

function meta(pares) {
  const dl = h("dl", { clase: "meta" });
  for (const [k, v] of pares) {
    if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) continue;
    dl.append(h("dt", {}, k), h("dd", {}, v));
  }
  return dl;
}

function fichaRegistro(d) {
  const doi = d.doi ? h("a", { href: "https://doi.org/" + d.doi, target: "_blank", rel: "noopener noreferrer" }, d.doi) : null;
  const abierto = d.oa_url && /^https?:\/\//.test(d.oa_url)
    ? h("a", { href: d.oa_url, target: "_blank", rel: "noopener noreferrer" }, "Texto abierto") : null;
  const manual = d.decidido_por && d.decidido_por !== "filtro";
  const decision = h("div", { clase: "caja" },
    h("h3", {}, "Decisión"),
    h("p", {}, h("span", { clase: "chip m-" + d.decision }, d.decision), " ", d.motivo),
    h("p", { clase: "tenue" }, `Decidido por: ${d.decidido_por || "filtro"}${d.categoria ? " · " + d.categoria : ""}`),
    manual && d.decision_filtro ? h("p", { clase: "tenue" }, `El filtro decía «${d.decision_filtro}»: ${d.motivo_filtro}`) : null,
    h("div", { clase: "fila-botones" },
      ...["incluir", "dudoso", "excluir"].map((x) =>
        h("button", { type: "button", clase: "boton chico " + x, onclick: () => decidir(d, x) },
          x === "incluir" ? "Incluir…" : x === "dudoso" ? "Dejar dudoso…" : "Excluir…"))),
  );
  return h("div", { clase: "ficha" },
    h("h2", {}, d.titulo),
    meta([
      ["Identificador", d.id], ["Autores", (d.autores || []).join("; ")], ["Año", d.anio], ["Revista", d.revista],
      ["Idioma", d.idioma], ["Tipo", d.tipo], ["DOI", doi], ["Acceso", abierto],
    ]),
    decision,
    h("div", {}, h("h3", {}, "Resumen"),
      h("p", { clase: "resumen-texto" }, d.resumen || "Sin resumen (NR). El cribado no lo descarta por eso: queda para una persona.")),
  );
}

function fichaNota(d) {
  const partes = [h("h2", {}, d.nombre)];
  const cabecera = h("p", {},
    d.estado ? h("span", { clase: "chip m-" + d.estado }, d.estado) : null, " ",
    h("span", { clase: "tenue" }, d.tipo && d.tipo !== "NR" ? d.tipo : "nota"));
  partes.push(cabecera);
  partes.push(meta([
    ["Fuentes", d.fuentes && d.fuentes.length ? d.fuentes.join("\n") : null],
    ["Alias", (d.alias || []).join(", ")],
    ["Confianza", d.confianza !== null && d.confianza !== undefined ? String(d.confianza) : null],
    ["Generada por", d.generado_por],
    ["Aprobada por", d.aprobado_por],
  ]));

  if (d.gestionada && !d.intacta) {
    partes.push(h("div", { clase: "caja aviso-caja" }, h("p", {}, "Editada a mano: Tatewari ya no la reescribe. Si llega información nueva, deja una propuesta.")));
  }
  if (!d.gestionada && d.tipo !== "fuente" && d.tipo !== "propuesta") {
    partes.push(h("div", { clase: "caja aviso-caja" }, h("p", {}, "Nota escrita por una persona o por ZEA MAYZ: sus estados se cambian en Obsidian.")));
  }
  if (d.conflictos && d.conflictos.length) {
    const lista = h("ul", {});
    for (const c of d.conflictos) {
      for (const v of c.versiones || []) lista.append(h("li", {}, `«${v.texto}» — ${v.documento}, ${v.ubicacion}`));
    }
    partes.push(h("div", { clase: "caja aviso-caja rojo" }, h("h3", {}, "Conflicto entre fuentes"),
      h("p", {}, "Tatewari no elige una versión: revisa las fuentes y edita la nota."), lista));
  }

  const botones = h("div", { clase: "fila-botones" });
  for (const nuevo of d.transiciones || []) {
    botones.append(h("button", { type: "button", clase: "boton chico" + (nuevo === "APPROVED" ? " primario" : ""), onclick: () => cambiarEstado(d, nuevo) }, NOMBRE_ESTADO[nuevo] || nuevo));
  }
  botones.append(h("a", { clase: "boton chico", href: d.obsidian }, "Abrir en Obsidian"));
  if (d.original) {
    botones.append(h("a", { clase: "boton chico", href: "/archivo?ruta=" + encodeURIComponent(d.original), target: "_blank", rel: "noopener" }, "Abrir original"));
  }
  partes.push(botones);
  partes.push(h("div", { clase: "md" }, ...markdown(d.cuerpo || "")));
  return h("div", { clase: "ficha" }, ...partes);
}

async function seguirEnlace(nombre, datoActual) {
  try {
    const d = await api("/api/nota?nombre=" + encodeURIComponent(nombre));
    if (datoActual) S.pila.push(datoActual);
    pintarFicha(d);
  } catch (e) {
    avisar(e.message);
  }
}

// ---------------------------------------------------------------------------
// Markdown (lo que escribe Tatewari: títulos, listas, citas, avisos, tablas)
// ---------------------------------------------------------------------------

function markdown(texto) {
  const lineas = texto.replace(/%%[\s\S]*?%%/g, "").split("\n");
  const bloques = [];
  let parrafo = [];
  const cerrarParrafo = () => { if (parrafo.length) { bloques.push(h("p", {}, ...enLinea(parrafo.join(" ")))); parrafo = []; } };

  for (let i = 0; i < lineas.length; i++) {
    const linea = lineas[i];
    if (/^```/.test(linea)) {
      cerrarParrafo();
      const codigo = [];
      for (i++; i < lineas.length && !/^```/.test(lineas[i]); i++) codigo.push(lineas[i]);
      bloques.push(h("pre", {}, codigo.join("\n")));
      continue;
    }
    const titulo = linea.match(/^(#{1,6})\s+(.*)$/);
    if (titulo) {
      cerrarParrafo();
      bloques.push(h("h" + Math.min(titulo[1].length, 4), {}, ...enLinea(titulo[2])));
      continue;
    }
    if (/^>/.test(linea)) {
      cerrarParrafo();
      const cita = [];
      for (; i < lineas.length && /^>/.test(lineas[i]); i++) cita.push(lineas[i].replace(/^>\s?/, ""));
      i--;
      bloques.push(bloqueCita(cita));
      continue;
    }
    if (/^\s*[-*]\s+/.test(linea)) {
      cerrarParrafo();
      const ul = h("ul", {});
      let li = null;
      for (; i < lineas.length; i++) {
        const l = lineas[i];
        const item = l.match(/^\s*[-*]\s+(.*)$/);
        if (item && !/^\s{2,}/.test(l)) { li = h("li", {}, ...enLinea(item[1])); ul.append(li); continue; }
        if (li && /^\s{2,}\S/.test(l)) {
          const resto = l.trim();
          if (resto.startsWith(">")) li.append(h("blockquote", {}, ...enLinea(resto.replace(/^>\s?/, ""))));
          else li.append(h("br"), ...enLinea(resto));
          continue;
        }
        break;
      }
      i--;
      bloques.push(ul);
      continue;
    }
    if (/^\|/.test(linea)) {
      cerrarParrafo();
      const filas = [];
      for (; i < lineas.length && /^\|/.test(lineas[i]); i++) filas.push(lineas[i]);
      i--;
      bloques.push(tabla(filas));
      continue;
    }
    if (!linea.trim()) { cerrarParrafo(); continue; }
    parrafo.push(linea.trim());
  }
  cerrarParrafo();
  return bloques;
}

function bloqueCita(lineas) {
  const primera = (lineas[0] || "").match(/^\[!(\w+)\]\s*(.*)$/);
  if (!primera) return h("blockquote", {}, ...lineas.flatMap((l, n) => (n ? [h("br"), ...enLinea(l)] : enLinea(l))));
  const caja = h("div", { clase: "callout " + primera[1].toLowerCase() });
  if (primera[2]) caja.append(h("div", { clase: "callout-titulo" }, ...enLinea(primera[2])));
  for (const l of lineas.slice(1)) if (l.trim()) caja.append(h("div", {}, ...enLinea(l)));
  return caja;
}

function tabla(filas) {
  const celdas = (f) => f.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const t = h("table", {});
  const cuerpo = filas.filter((f) => !/^\|\s*:?-{2,}/.test(f));
  cuerpo.forEach((f, n) => t.append(h("tr", {}, ...celdas(f).map((c) => h(n ? "td" : "th", {}, ...enLinea(c))))));
  return t;
}

function enLinea(texto) {
  const patron = /(\[\[[^\]]+\]\])|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(`[^`]+`)|(https?:\/\/[^\s)»]+)/g;
  const salida = [];
  let ultimo = 0;
  let m;
  while ((m = patron.exec(texto))) {
    if (m.index > ultimo) salida.push(texto.slice(ultimo, m.index));
    const t = m[0];
    if (m[1]) {
      const [destino, alias] = t.slice(2, -2).split("|");
      const enlace = h("a", { clase: "wikilink", href: "#", title: destino }, alias || destino);
      enlace.addEventListener("click", (ev) => { ev.preventDefault(); seguirEnlace(destino, ultimaFicha()); });
      salida.push(enlace);
    } else if (m[2]) salida.push(h("strong", {}, ...enLinea(t.slice(2, -2))));
    else if (m[3]) salida.push(h("em", {}, ...enLinea(t.slice(1, -1))));
    else if (m[4]) salida.push(h("code", {}, t.slice(1, -1)));
    else salida.push(h("a", { href: t, target: "_blank", rel: "noopener noreferrer" }, t));
    ultimo = m.index + t.length;
  }
  if (ultimo < texto.length) salida.push(texto.slice(ultimo));
  return salida;
}

function ultimaFicha() { return S.fichaActual; }

// ---------------------------------------------------------------------------
// Acciones
// ---------------------------------------------------------------------------

async function decidir(registro, decision) {
  $("decidir-titulo").textContent = `Decidir ${registro.id}`;
  $("decidir-registro").textContent = registro.titulo;
  for (const r of document.querySelectorAll('#decidir-opciones input')) r.checked = r.value === decision;
  $("decidir-motivo").value = "";
  $("decidir-autor").value = autor();
  if (!(await abrirDialogo("dlg-decidir"))) return;
  const elegida = document.querySelector('#decidir-opciones input:checked');
  const datos = {
    revision: registro.revision, id: registro.id, decision: elegida ? elegida.value : decision,
    motivo: $("decidir-motivo").value, autor: $("decidir-autor").value,
  };
  guardar("tatewari_autor", datos.autor.trim());
  try {
    const nuevo = await api("/api/decidir", { json: datos });
    avisar(`${registro.id}: ${nuevo.decision}. Guardado en decisiones.json.`);
    await recargarArbol();
    await recargarElementos();
  } catch (e) {
    avisar(e.message, true);
  }
}

async function cambiarEstado(nota, nuevo) {
  const humano = nuevo === "APPROVED" || nuevo === "PUBLISHED";
  $("estado-titulo").textContent = `${NOMBRE_ESTADO[nuevo] || nuevo}: ${nota.nombre}`;
  $("estado-explicacion").textContent = humano
    ? "Solo una persona aprueba o publica. Hazlo después de leer la nota contra su fuente. Desde entonces Tatewari no la reescribe."
    : `La nota pasa a ${nuevo}.`;
  $("estado-autor").value = autor();
  $("estado-autor").required = humano;
  $("estado-ok").textContent = NOMBRE_ESTADO[nuevo] || "Cambiar";
  if (!(await abrirDialogo("dlg-estado"))) return;
  const firma = $("estado-autor").value.trim();
  guardar("tatewari_autor", firma);
  try {
    const d = await api("/api/estado-nota", { json: { id: nota.id, estado: nuevo, autor: firma } });
    avisar(`«${d.nombre}» ahora está en ${d.estado}.`);
    await recargarArbol();
    await recargarElementos();
    pintarFicha(d);
  } catch (e) {
    avisar(e.message, true);
  }
}

async function configurarVault() {
  $("vault-ruta").value = (S.estado && S.estado.vault_configurado) || "";
  if (!(await abrirDialogo("dlg-vault"))) return;
  try {
    const r = await api("/api/vault", { json: { ruta: $("vault-ruta").value, recordar: $("vault-recordar").checked } });
    avisar(`Vault listo: ${r.vault}` + (r.env ? `\nGuardado en ${r.env}` : ""));
    S.estado = await api("/api/estado");
    await recargarArbol();
    await elegirColeccion("vault:todas");
  } catch (e) {
    avisar(e.message, true);
  }
}

async function anadirDocumentos() {
  if (!S.estado.vault) { await configurarVault(); if (!S.estado.vault) return; }
  $("archivos").value = "";
  $("ruta-doc").value = "";
  if (!(await abrirDialogo("dlg-anadir"))) return;
  const archivos = [...$("archivos").files];
  if (archivos.length) await subir(archivos);
  const ruta = $("ruta-doc").value.trim();
  if (ruta) {
    try {
      await api("/api/procesar", { json: { ruta } });
      avisar("Documento en cola. Mira el avance abajo.");
      sondearTrabajos(true);
    } catch (e) { avisar(e.message, true); }
  }
  if (!archivos.length && !ruta) avisar("No elegiste ningún documento.");
}

async function subir(archivos) {
  if (!S.estado.vault) { await configurarVault(); if (!S.estado.vault) return; }
  const admitidos = S.estado.tipos_admitidos;
  for (const archivo of archivos) {
    const extension = "." + archivo.name.split(".").pop().toLowerCase();
    if (!admitidos.includes(extension)) { avisar(`«${archivo.name}» no se admite (${admitidos.join(", ")}).`, true); continue; }
    try {
      await api("/api/subir?nombre=" + encodeURIComponent(archivo.name), { cuerpo: archivo });
      avisar(`«${archivo.name}» en cola.`);
    } catch (e) { avisar(e.message, true); }
  }
  sondearTrabajos(true);
}

async function trabajoSimple(ruta, datos, mensaje) {
  try {
    await api(ruta, { json: datos || {} });
    avisar(mensaje);
    sondearTrabajos(true);
  } catch (e) { avisar(e.message, true); }
}

async function divulgar() {
  if (!(await abrirDialogo("dlg-divulgar"))) return;
  trabajoSimple("/api/divulgar", { tema: $("divulgar-tema").value, publico: $("divulgar-publico").value },
    "Borrador en cola. Tarda uno o dos minutos con un modelo de 4B.");
}

async function validar() {
  try {
    const r = await api("/api/validar", { json: {} });
    mostrarTexto("Validación del Vault", [r.resumen, ...r.errores.map((x) => "✗ " + x), ...r.avisos.map((x) => "! " + x)].join("\n"));
  } catch (e) { avisar(e.message, true); }
}

function mostrarTexto(titulo, texto) {
  $("texto-titulo").textContent = titulo;
  $("texto-cuerpo").textContent = texto;
  $("dlg-texto").showModal();
}

// ---------------------------------------------------------------------------
// Modelo y trabajos
// ---------------------------------------------------------------------------

async function consultarModelo() {
  const luz = $("modelo-luz"), texto = $("modelo-texto"), boton = $("modelo");
  try {
    const m = await api("/api/modelos");
    if (!m.ok) {
      luz.className = "luz apagada";
      texto.textContent = "Ollama no responde";
      boton.title = m.error;
      return;
    }
    const nombre = m.tareas.extraccion;
    const cargado = m.en_memoria.some((x) => x === nombre || x.split(":")[0] === nombre);
    const cargando = !cargado && S.trabajos.some((t) => t.titulo === "Cargar el modelo" && t.estado === "en_curso");
    luz.className = "luz " + (cargado ? "lista" : cargando ? "cargando" : "fria");
    texto.textContent = `${nombre} · ${cargado ? "cargado" : cargando ? "cargando…" : "sin cargar"}`;
    boton.title = `Extracción: ${m.tareas.extraccion}\nSíntesis: ${m.tareas.sintesis}\nEn memoria: ${m.en_memoria.join(", ") || "ninguno"}\n` +
      (cargado ? "" : "Pulsa para cargarlo en la tarjeta.");
    boton.dataset.cargado = cargado ? "1" : "";
  } catch (e) {
    luz.className = "luz apagada";
    texto.textContent = "Sin conexión con Tatewari";
    boton.title = e.message;
  }
}

async function sondearTrabajos(inmediato) {
  clearTimeout(S.sondeo);
  try {
    S.trabajos = await api("/api/trabajos");
  } catch (e) {
    S.sondeo = setTimeout(sondearTrabajos, 5000);
    return;
  }
  pintarTrabajos();
  const cargaba = $("modelo-texto").textContent.endsWith("cargando…");
  const carga = S.trabajos.some((t) => t.titulo === "Cargar el modelo" && t.estado === "en_curso");
  if (cargaba !== carga) consultarModelo();
  const activos = S.trabajos.some((t) => t.estado === "en_cola" || t.estado === "en_curso");
  for (const t of S.trabajos) {
    if ((t.estado === "hecho" || t.estado === "fallo") && !S.vistos.has(t.id)) {
      S.vistos.add(t.id);
      if (inmediato !== "primera") terminado(t);
    }
  }
  S.sondeo = setTimeout(sondearTrabajos, activos ? 1200 : 6000);
}

async function terminado(t) {
  if (t.estado === "fallo") avisar(`${t.titulo}: ${t.resultado}`, true);
  else avisar(`${t.titulo}: terminado.`);
  consultarModelo();
  await recargarArbol();
  await recargarElementos();
}

function pintarTrabajos() {
  const actual = S.trabajos.find((t) => t.estado === "en_curso") || S.trabajos.find((t) => t.estado === "en_cola") || S.trabajos[0];
  const rueda = $("rueda"), texto = $("actividad-texto");
  if (!actual) { rueda.className = "rueda"; texto.textContent = "Sin trabajos en curso"; }
  else {
    const enCola = S.trabajos.filter((t) => t.estado === "en_cola").length;
    rueda.className = "rueda " + (actual.estado === "en_curso" || actual.estado === "en_cola" ? "girando" : actual.estado);
    const ultima = actual.lineas.length ? " — " + actual.lineas[actual.lineas.length - 1].trim() : "";
    texto.textContent = actual.estado === "en_curso"
      ? `${actual.titulo}${ultima}${enCola ? ` (+${enCola} en cola)` : ""}`
      : actual.estado === "en_cola" ? `${actual.titulo}: en cola` : `${actual.titulo}: ${actual.estado === "hecho" ? "terminado" : "falló"}`;
  }
  if (!$("trabajos").hidden) pintarListaTrabajos();
}

function pintarListaTrabajos() {
  const nombres = { en_cola: "en cola", en_curso: "en curso", hecho: "terminado", fallo: "falló" };
  $("lista-trabajos").replaceChildren(...(S.trabajos.length ? S.trabajos.map((t) =>
    h("li", { clase: "trabajo" },
      h("div", { clase: "trabajo-cabeza" },
        h("span", { clase: "rueda " + (t.estado === "en_curso" || t.estado === "en_cola" ? "girando" : t.estado) }),
        t.titulo, h("span", { clase: "tenue" }, `${nombres[t.estado]}${t.segundos ? ` · ${t.segundos} s` : ""}`)),
      (t.resultado || t.lineas.length) ? h("pre", { clase: "consola" }, t.resultado || t.lineas.join("\n")) : null,
    )) : [h("li", { clase: "tenue" }, "Todavía no has lanzado ningún trabajo.")]));
}

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------

function prepararEventos() {
  $("b-anadir").addEventListener("click", anadirDocumentos);
  $("b-materia").addEventListener("click", () => trabajoSimple("/api/materia", {}, "Analizando la materia. Lo ya procesado se salta."));
  $("b-divulgar").addEventListener("click", divulgar);
  $("b-validar").addEventListener("click", validar);
  $("modelo").addEventListener("click", () => {
    if ($("modelo").dataset.cargado || $("modelo-texto").textContent.endsWith("cargando…")) {
      avisar($("modelo").title || "El modelo se está cargando.");
      return;
    }
    trabajoSimple("/api/precargar", {}, "Cargando el modelo en la tarjeta…");
  });
  $("actividad").addEventListener("click", () => {
    const panel = $("trabajos");
    panel.hidden = !panel.hidden;
    $("actividad").setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) pintarListaTrabajos();
  });
  $("cerrar-trabajos").addEventListener("click", () => { $("trabajos").hidden = true; $("actividad").setAttribute("aria-expanded", "false"); });

  let espera = null;
  $("buscar").addEventListener("input", (ev) => {
    clearTimeout(espera);
    espera = setTimeout(() => { S.consulta = ev.target.value.trim(); recargarElementos(); }, 250);
  });

  document.addEventListener("keydown", (ev) => {
    const escribiendo = /INPUT|TEXTAREA/.test(document.activeElement.tagName) || document.querySelector("dialog[open]");
    if (ev.key === "/" && !escribiendo) { ev.preventDefault(); $("buscar").focus(); return; }
    if (escribiendo || !S.elementos.length) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const filas = [...$("tabla-cuerpo").rows];
      const actual = filas.findIndex((tr) => tr.dataset.id === S.seleccion);
      const siguiente = Math.max(0, Math.min(filas.length - 1, actual + (ev.key === "ArrowDown" ? 1 : -1)));
      if (filas[siguiente]) seleccionar(filas[siguiente].dataset.id);
    }
  });

  // Arrastrar documentos a cualquier parte de la ventana.
  let profundidad = 0;
  const soltar = $("soltar");
  const conArchivos = (ev) => ev.dataTransfer && [...ev.dataTransfer.types].includes("Files");
  window.addEventListener("dragenter", (ev) => { if (!conArchivos(ev)) return; ev.preventDefault(); profundidad++; soltar.hidden = false; });
  window.addEventListener("dragover", (ev) => { if (conArchivos(ev)) ev.preventDefault(); });
  window.addEventListener("dragleave", () => { profundidad = Math.max(0, profundidad - 1); if (!profundidad) soltar.hidden = true; });
  window.addEventListener("drop", (ev) => {
    if (!conArchivos(ev)) return;
    ev.preventDefault();
    profundidad = 0;
    soltar.hidden = true;
    subir([...ev.dataTransfer.files]);
  });
}

function prepararSeparadores() {
  const raiz = document.documentElement;
  const anchos = leer("tatewari_anchos", {});
  if (anchos.arbol) raiz.style.setProperty("--ancho-arbol", anchos.arbol + "px");
  if (anchos.detalle) raiz.style.setProperty("--ancho-detalle", anchos.detalle + "px");
  for (const sep of document.querySelectorAll(".separador")) {
    const panel = sep.dataset.panel;
    const fijar = (px) => {
      const valor = Math.max(170, Math.min(px, window.innerWidth * 0.5));
      raiz.style.setProperty(panel === "arbol" ? "--ancho-arbol" : "--ancho-detalle", valor + "px");
      anchos[panel] = Math.round(valor);
      guardar("tatewari_anchos", anchos);
    };
    sep.addEventListener("pointerdown", (ev) => {
      sep.setPointerCapture(ev.pointerId);
      sep.classList.add("activo");
      const mover = (e) => fijar(panel === "arbol" ? e.clientX : window.innerWidth - e.clientX);
      const soltarSep = () => { sep.classList.remove("activo"); sep.removeEventListener("pointermove", mover); sep.removeEventListener("pointerup", soltarSep); };
      sep.addEventListener("pointermove", mover);
      sep.addEventListener("pointerup", soltarSep);
    });
    sep.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      const actual = $(panel === "arbol" ? "arbol" : "detalle").getBoundingClientRect().width;
      const paso = (ev.key === "ArrowRight" ? 1 : -1) * (panel === "arbol" ? 20 : -20);
      fijar(actual + paso);
    });
  }
}

document.addEventListener("DOMContentLoaded", arrancar);
