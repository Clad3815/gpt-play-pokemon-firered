### Example code for the pathfinding tool
# To replace with the actual code


# Tile IDs (as per provided legend)
WALL = 0
FREE = 1
TALL_GRASS = 2
.... (Full list of tile IDs)

DIRS = {
    'up': (0, -1),
    'down': (0, 1),
    'left': (-1, 0),
    'right': (1, 0),
}

LEDGE_DIR = {
    LEDGE_DOWN: (0, 1),
    LEDGE_RIGHT: (1, 0),
    LEDGE_LEFT: (-1, 0),
}

def load_grid(path: str):
    with open(path, 'r') as f:
        return json.load(f)

### .....
### Rest of the code here (TODO: Replace with the actual code)

if __name__ == '__main__':
    # Example usage:
    grid_path = 'temp_map_grid.json'
    start = (7, 12)
    goal = (4, 15)
    keys, meta = plan_path(grid_path, start, goal)
    print(keys)
    print(meta) ## Debug information about the path (Tiles visited, etc ...)
