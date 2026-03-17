import numpy as np
import random
from simulate_weights import build_fast_dataset

# Configuration for Genetic Algorithm
POPULATION_SIZE = 50
GENERATIONS = 100
MUTATION_RATE = 0.1
CROSSOVER_RATE = 0.8
NUM_FEATURES = 6 # [sim_title, sim_desc, sim_domains, sim_actors, sim_usecases, sim_lexical]

def initialize_population(size, num_features):
    """Generate initial population of random weight vectors normalized to sum to 1.0"""
    population = []
    for _ in range(size):
        weights = np.random.rand(num_features)
        weights = weights / np.sum(weights)
        population.append(weights)
    return population

def calculate_fitness(weights, X, y):
    """
    Calculate fitness as retrieval accuracy.
    A case is 'retrieved' if its weighted similarity score is above the median threshold
    and it matches the ground truth label.
    """
    scores = np.dot(X, weights)
    
    # We use a simple threshold-based retrieval simulation for the fitness function
    # In a real CBR system, we'd rank and measure precision@k or similar
    threshold = np.median(scores) if len(scores) > 0 else 0.5
    
    predictions = (scores >= threshold).astype(int)
    
    # Accuracy: (True Positives + True Negatives) / Total
    correct = np.sum(predictions == y)
    accuracy = correct / len(y) if len(y) > 0 else 0
    return accuracy

def select_parents(population, fitness_scores, k=3):
    """Tournament selection"""
    selected = []
    for _ in range(2): # Need two parents
        indices = np.random.choice(len(population), min(k, len(population)), replace=False)
        best_idx = indices[np.argmax([fitness_scores[i] for i in indices])]
        selected.append(population[best_idx])
    return selected[0], selected[1]

def crossover(parent1, parent2):
    """Uniform crossover"""
    child = np.copy(parent1)
    if random.random() < CROSSOVER_RATE:
        mask = np.random.choice([0, 1], size=NUM_FEATURES).astype(bool)
        child[mask] = parent2[mask]
        
    # Re-normalize
    tot = np.sum(child)
    if tot > 0:
        child = child / tot
    else:
        child = np.ones(NUM_FEATURES) / NUM_FEATURES
    return child

def mutate(individual):
    """Random Gaussian mutation"""
    if random.random() < MUTATION_RATE:
        mutation = np.random.normal(0, 0.1, NUM_FEATURES)
        individual = individual + mutation
        
        # Ensure weights are positive
        individual = np.maximum(individual, 0.0001)
        
        # Re-normalize
        individual = individual / np.sum(individual)
    return individual

def run_genetic_algorithm(X, y):
    print("\n--- Running Genetic Algorithm for Weight Optimization ---")
    
    population = initialize_population(POPULATION_SIZE, NUM_FEATURES)
    best_weights = None
    best_fitness = -1
    
    for generation in range(GENERATIONS):
        fitness_scores = [calculate_fitness(w, X, y) for w in population]
        
        # Track best
        current_best_idx = np.argmax(fitness_scores)
        if fitness_scores[current_best_idx] > best_fitness:
            best_fitness = fitness_scores[current_best_idx]
            best_weights = np.copy(population[current_best_idx])
            
        if generation % 20 == 0 or generation == GENERATIONS - 1:
            print(f"Generation {generation:3d} | Best Accuracy: {best_fitness:.4f}")
            
        # Create next generation
        new_population = []
        
        # Elitism: keep best
        new_population.append(np.copy(population[current_best_idx]))
        
        while len(new_population) < POPULATION_SIZE:
            parent1, parent2 = select_parents(population, fitness_scores)
            child = crossover(parent1, parent2)
            child = mutate(child)
            new_population.append(child)
            
        population = new_population
        
    feature_names = ["System Name", "Description", "Domains", "Actors", "Use Cases", "Lexical"]
    
    print("\n🏆 Ideal Weights from Genetic Algorithm:")
    for name, w in zip(feature_names, best_weights):
        print(f" - {name:<15}: {w:.4f} ({w*100:.1f}%)")
        
    return best_weights

if __name__ == "__main__":
    X, y = build_fast_dataset()
    if len(X) > 0:
        run_genetic_algorithm(X, y)
