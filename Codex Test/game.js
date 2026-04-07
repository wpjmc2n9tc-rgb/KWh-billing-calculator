const canvas = document.getElementById("gameCanvas");
const ctx = canvas.getContext("2d");

const toolbarEl = document.getElementById("toolbar");
const inventoryEl = document.getElementById("inventory");
const goalTextEl = document.getElementById("goalText");
const selectedToolEl = document.getElementById("selectedTool");
const rotationLabelEl = document.getElementById("rotationLabel");
const statusTextEl = document.getElementById("statusText");

const TILE_SIZE = 64;
const GRID_WIDTH = 15;
const GRID_HEIGHT = 10;
const SIMULATION_STEP_MS = 220;
const directions = ["up", "right", "down", "left"];
const directionVectors = {
  up: { x: 0, y: -1 },
  right: { x: 1, y: 0 },
  down: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
};

const buildings = {
  miner: {
    label: "Miner",
    cost: { plate: 4 },
    description: "Baut Erz auf einer Quelle ab.",
  },
  belt: {
    label: "Band",
    cost: { plate: 1 },
    description: "Transportiert Items.",
  },
  furnace: {
    label: "Ofen",
    cost: { plate: 6 },
    description: "Schmilzt Erz zu Platten.",
  },
  assembler: {
    label: "Assembler",
    cost: { plate: 8, gear: 2 },
    description: "Baut Zahnräder.",
  },
  storage: {
    label: "Lager",
    cost: { plate: 5 },
    description: "Sammelt fertige Items.",
  },
};

const state = {
  selectedTool: "belt",
  rotationIndex: 1,
  inventory: {
    ore: 0,
    plate: 28,
    gear: 4,
  },
  delivered: {
    ore: 0,
    plate: 0,
    gear: 0,
  },
  goal: {
    gear: 12,
  },
  message: "Baue eine kleine Produktionskette bis ins Lager.",
  grid: [],
};

function createTile(x, y) {
  return {
    x,
    y,
    terrain: "ground",
    building: null,
    item: null,
  };
}

function initializeGrid() {
  for (let y = 0; y < GRID_HEIGHT; y += 1) {
    const row = [];
    for (let x = 0; x < GRID_WIDTH; x += 1) {
      row.push(createTile(x, y));
    }
    state.grid.push(row);
  }

  const orePatches = [
    [2, 2], [3, 2], [2, 3], [3, 3], [4, 3],
    [10, 5], [11, 5], [10, 6],
  ];

  for (const [x, y] of orePatches) {
    state.grid[y][x].terrain = "ore";
  }
}

function setStarterLayout() {
  placeBuilding(2, 2, "miner", "right", true);
  placeBuilding(3, 2, "belt", "right", true);
  placeBuilding(4, 2, "belt", "down", true);
  placeBuilding(4, 3, "furnace", "down", true);
  placeBuilding(4, 4, "belt", "right", true);
  placeBuilding(5, 4, "belt", "right", true);
  placeBuilding(6, 4, "assembler", "down", true);
  placeBuilding(6, 5, "belt", "right", true);
  placeBuilding(7, 5, "storage", "right", true);
}

function currentDirection() {
  return directions[state.rotationIndex];
}

function getTile(x, y) {
  if (x < 0 || y < 0 || x >= GRID_WIDTH || y >= GRID_HEIGHT) {
    return null;
  }
  return state.grid[y][x];
}

function canAfford(cost) {
  return Object.entries(cost).every(([key, value]) => state.inventory[key] >= value);
}

function spendResources(cost) {
  for (const [key, value] of Object.entries(cost)) {
    state.inventory[key] -= value;
  }
}

function refundResources(type) {
  const cost = buildings[type].cost;
  for (const [key, value] of Object.entries(cost)) {
    state.inventory[key] += Math.ceil(value / 2);
  }
}

function updateHud() {
  selectedToolEl.textContent = buildings[state.selectedTool].label;
  rotationLabelEl.textContent = currentDirection();
  statusTextEl.textContent = state.message;
  goalTextEl.textContent = `Liefere ${state.goal.gear} Zahnräder ins Lager. Aktuell: ${state.delivered.gear}/${state.goal.gear}`;

  inventoryEl.innerHTML = "";
  const entries = [
    ["Erz", state.inventory.ore],
    ["Platten", state.inventory.plate],
    ["Zahnräder", state.inventory.gear],
    ["Gelagertes Erz", state.delivered.ore],
    ["Gelagerte Platten", state.delivered.plate],
    ["Gelagerte Zahnräder", state.delivered.gear],
  ];

  for (const [label, value] of entries) {
    const card = document.createElement("div");
    card.className = "stat-card";
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    inventoryEl.appendChild(card);
  }
}

function renderToolbar() {
  toolbarEl.innerHTML = "";
  for (const [key, data] of Object.entries(buildings)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tool-button ${state.selectedTool === key ? "active" : ""}`;
    button.innerHTML = `<strong>${data.label}</strong><span>${data.description}</span>`;
    button.addEventListener("click", () => {
      state.selectedTool = key;
      state.message = `${data.label} ausgewahlt.`;
      renderToolbar();
      updateHud();
    });
    toolbarEl.appendChild(button);
  }
}

function placeBuilding(x, y, type, direction, ignoreCost = false) {
  const tile = getTile(x, y);
  if (!tile || tile.building) {
    return false;
  }

  if (type === "miner" && tile.terrain !== "ore") {
    return false;
  }

  if (!ignoreCost && !canAfford(buildings[type].cost)) {
    return false;
  }

  if (!ignoreCost) {
    spendResources(buildings[type].cost);
  }

  tile.building = {
    type,
    direction,
    progress: 0,
    buffer: [],
  };
  return true;
}

function removeBuilding(x, y) {
  const tile = getTile(x, y);
  if (!tile || !tile.building) {
    return false;
  }

  if (tile.item) {
    state.inventory[tile.item.type] += 1;
    tile.item = null;
  }

  refundResources(tile.building.type);
  tile.building = null;
  return true;
}

function addItemToTile(tile, itemType, progress = 0) {
  if (!tile || tile.item) {
    return false;
  }
  tile.item = { type: itemType, progress };
  return true;
}

function storeItem(itemType) {
  state.delivered[itemType] += 1;
  state.inventory[itemType] += 1;
  if (itemType === "gear" && state.delivered.gear >= state.goal.gear) {
    state.message = "Ziel erreicht. Deine Fabrik liefert Zahnrader.";
  }
}

function moveTileItem(tile, direction) {
  if (!tile.item) {
    return;
  }

  const vector = directionVectors[direction];
  const target = getTile(tile.x + vector.x, tile.y + vector.y);
  if (!target) {
    tile.item = null;
    return;
  }

  if (target.building?.type === "storage") {
    storeItem(tile.item.type);
    tile.item = null;
    return;
  }

  if (target.building?.type === "furnace" || target.building?.type === "assembler") {
    if (target.building.buffer.length < 2) {
      target.building.buffer.push(tile.item.type);
      tile.item = null;
    }
    return;
  }

  if (target.item) {
    return;
  }

  tile.item.progress = 0;
  target.item = tile.item;
  tile.item = null;
}

function processMiner(tile) {
  const building = tile.building;
  building.progress += 1;
  if (building.progress < 3) {
    return;
  }
  if (!tile.item) {
    tile.item = { type: "ore", progress: 0 };
    building.progress = 0;
  }
}

function processFurnace(tile) {
  const building = tile.building;
  if (tile.item) {
    return;
  }
  const oreIndex = building.buffer.indexOf("ore");
  if (oreIndex === -1) {
    return;
  }
  building.progress += 1;
  if (building.progress < 4) {
    return;
  }
  building.buffer.splice(oreIndex, 1);
  tile.item = { type: "plate", progress: 0 };
  building.progress = 0;
}

function processAssembler(tile) {
  const building = tile.building;
  if (tile.item) {
    return;
  }
  const plates = building.buffer.filter((item) => item === "plate").length;
  if (plates < 2) {
    return;
  }
  building.progress += 1;
  if (building.progress < 5) {
    return;
  }
  let removed = 0;
  building.buffer = building.buffer.filter((item) => {
    if (item === "plate" && removed < 2) {
      removed += 1;
      return false;
    }
    return true;
  });
  tile.item = { type: "gear", progress: 0 };
  building.progress = 0;
}

function processBelt(tile) {
  if (!tile.item) {
    return;
  }
  tile.item.progress += 0.34;
  if (tile.item.progress >= 1) {
    moveTileItem(tile, tile.building.direction);
  }
}

function processStorage(tile) {
  if (tile.item) {
    storeItem(tile.item.type);
    tile.item = null;
  }
}

function processMachineOutput(tile) {
  if (!tile.item || !tile.building?.direction) {
    return;
  }
  moveTileItem(tile, tile.building.direction);
}

function simulationTick() {
  for (let y = 0; y < GRID_HEIGHT; y += 1) {
    for (let x = 0; x < GRID_WIDTH; x += 1) {
      const tile = state.grid[y][x];
      if (!tile.building) {
        continue;
      }
      switch (tile.building.type) {
        case "miner":
          processMiner(tile);
          break;
        case "furnace":
          processFurnace(tile);
          break;
        case "assembler":
          processAssembler(tile);
          break;
        case "storage":
          processStorage(tile);
          break;
        default:
          break;
      }
    }
  }

  for (let y = GRID_HEIGHT - 1; y >= 0; y -= 1) {
    for (let x = GRID_WIDTH - 1; x >= 0; x -= 1) {
      const tile = state.grid[y][x];
      if (tile.building?.type === "belt") {
        processBelt(tile);
      }
    }
  }

  for (let y = GRID_HEIGHT - 1; y >= 0; y -= 1) {
    for (let x = GRID_WIDTH - 1; x >= 0; x -= 1) {
      const tile = state.grid[y][x];
      if (["miner", "furnace", "assembler"].includes(tile.building?.type)) {
        processMachineOutput(tile);
      }
    }
  }

  updateHud();
}

function drawGrid() {
  for (let y = 0; y < GRID_HEIGHT; y += 1) {
    for (let x = 0; x < GRID_WIDTH; x += 1) {
      const tile = state.grid[y][x];
      const px = x * TILE_SIZE;
      const py = y * TILE_SIZE;

      ctx.fillStyle = tile.terrain === "ore" ? "#8a7b72" : "#c8a36d";
      ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);

      ctx.strokeStyle = "rgba(50, 38, 24, 0.15)";
      ctx.strokeRect(px, py, TILE_SIZE, TILE_SIZE);

      if (tile.terrain === "ore") {
        ctx.fillStyle = "rgba(38, 45, 55, 0.35)";
        ctx.beginPath();
        ctx.arc(px + 20, py + 24, 8, 0, Math.PI * 2);
        ctx.arc(px + 40, py + 34, 10, 0, Math.PI * 2);
        ctx.arc(px + 28, py + 44, 6, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

function drawArrow(centerX, centerY, direction, color) {
  ctx.save();
  ctx.translate(centerX, centerY);
  const angles = {
    up: -Math.PI / 2,
    right: 0,
    down: Math.PI / 2,
    left: Math.PI,
  };
  ctx.rotate(angles[direction]);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(-14, -10);
  ctx.lineTo(8, -10);
  ctx.lineTo(8, -18);
  ctx.lineTo(18, 0);
  ctx.lineTo(8, 18);
  ctx.lineTo(8, 10);
  ctx.lineTo(-14, 10);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawBuildings() {
  for (let y = 0; y < GRID_HEIGHT; y += 1) {
    for (let x = 0; x < GRID_WIDTH; x += 1) {
      const tile = state.grid[y][x];
      if (!tile.building) {
        continue;
      }

      const px = x * TILE_SIZE;
      const py = y * TILE_SIZE;
      const centerX = px + TILE_SIZE / 2;
      const centerY = py + TILE_SIZE / 2;
      const building = tile.building;

      switch (building.type) {
        case "miner":
          ctx.fillStyle = "#4d7b8a";
          ctx.fillRect(px + 8, py + 8, 48, 48);
          drawArrow(centerX, centerY, building.direction, "#dff4f7");
          break;
        case "belt":
          ctx.fillStyle = "#7a532e";
          ctx.fillRect(px + 8, py + 18, 48, 28);
          drawArrow(centerX, centerY, building.direction, "#f5d8a9");
          break;
        case "furnace":
          ctx.fillStyle = "#6f5546";
          ctx.fillRect(px + 8, py + 8, 48, 48);
          ctx.fillStyle = "#ec8a3c";
          ctx.fillRect(px + 20, py + 20, 24, 24);
          break;
        case "assembler":
          ctx.fillStyle = "#40634a";
          ctx.fillRect(px + 8, py + 8, 48, 48);
          ctx.strokeStyle = "#d2e6d4";
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.arc(centerX, centerY, 13, 0, Math.PI * 2);
          ctx.stroke();
          break;
        case "storage":
          ctx.fillStyle = "#9a7442";
          ctx.fillRect(px + 8, py + 8, 48, 48);
          ctx.strokeStyle = "#f6e1ba";
          ctx.lineWidth = 3;
          ctx.strokeRect(px + 18, py + 18, 28, 28);
          break;
        default:
          break;
      }

      if (building.buffer.length > 0) {
        ctx.fillStyle = "rgba(255, 255, 255, 0.86)";
        ctx.fillRect(px + 4, py + 4, 18, 18);
        ctx.fillStyle = "#24303b";
        ctx.font = "12px Georgia";
        ctx.fillText(String(building.buffer.length), px + 10, py + 17);
      }
    }
  }
}

function drawItem(tile) {
  if (!tile.item) {
    return;
  }

  const px = tile.x * TILE_SIZE;
  const py = tile.y * TILE_SIZE;
  const item = tile.item;
  const offsetX = tile.building?.type === "belt" ? directionVectors[tile.building.direction].x * item.progress * 18 : 0;
  const offsetY = tile.building?.type === "belt" ? directionVectors[tile.building.direction].y * item.progress * 18 : 0;
  const centerX = px + TILE_SIZE / 2 + offsetX;
  const centerY = py + TILE_SIZE / 2 + offsetY;

  const colors = {
    ore: "#424852",
    plate: "#cfd4db",
    gear: "#d68b2d",
  };

  ctx.fillStyle = colors[item.type];
  ctx.beginPath();
  ctx.arc(centerX, centerY, 10, 0, Math.PI * 2);
  ctx.fill();

  if (item.type === "gear") {
    ctx.strokeStyle = "#73470f";
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(centerX, centerY, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#73470f";
    ctx.fill();
  }
}

function render() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawGrid();
  drawBuildings();

  for (let y = 0; y < GRID_HEIGHT; y += 1) {
    for (let x = 0; x < GRID_WIDTH; x += 1) {
      drawItem(state.grid[y][x]);
    }
  }

  requestAnimationFrame(render);
}

function cellFromMouseEvent(event) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const x = Math.floor(((event.clientX - rect.left) * scaleX) / TILE_SIZE);
  const y = Math.floor(((event.clientY - rect.top) * scaleY) / TILE_SIZE);
  return { x, y };
}

function handleBuild(event) {
  const { x, y } = cellFromMouseEvent(event);
  if (event.button === 2) {
    const removed = removeBuilding(x, y);
    state.message = removed ? "Gebaude entfernt und halb erstattet." : "Dort gibt es nichts zu entfernen.";
    updateHud();
    return;
  }

  const success = placeBuilding(x, y, state.selectedTool, currentDirection());
  if (success) {
    state.message = `${buildings[state.selectedTool].label} gebaut.`;
  } else {
    state.message = "Bau nicht moglich: Feld belegt, falscher Untergrund oder zu wenig Ressourcen.";
  }
  updateHud();
}

canvas.addEventListener("mousedown", handleBuild);
canvas.addEventListener("contextmenu", (event) => event.preventDefault());

window.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "r") {
    state.rotationIndex = (state.rotationIndex + 1) % directions.length;
    state.message = `Richtung auf ${currentDirection()} gedreht.`;
    updateHud();
  }
});

initializeGrid();
setStarterLayout();
renderToolbar();
updateHud();
render();
setInterval(simulationTick, SIMULATION_STEP_MS);
