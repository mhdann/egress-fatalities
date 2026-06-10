# ----------------------
# 1. Load libraries
# ----------------------
library(tidyverse)
library(sf)
library(rnaturalearth)
library(rnaturalearthdata)
library(RColorBrewer)
library(scales)
library(tidycensus)
library(ggpubr)
library(biscale)

# ----------------------
# 2. Read and inspect data
# ----------------------
roads <- read.csv("~/papers/roads/august_combined_data.csv") #point to your directory
glimpse(roads)

# ----------------------
# 3. Prepare spatial data and population data
# ----------------------
states <- ne_states(country = "United States of America", returnclass = "sf")
pop_data <- get_acs(geography = "state", variables = "B01003_001", year = 2021) %>%
  rename(state_population = estimate)
states <- merge(states, pop_data, by.x = "name", by.y = "NAME", all.x = TRUE)

# ----------------------
# 4. Data cleaning and variable engineering
# ----------------------
roads <- roads %>%
  filter(Total.Popu > 0) %>%
  rename(state = state_x) %>%
  mutate(
    exits = (boundary_crossing_edges_motorway + boundary_crossing_edges_trunk +
               boundary_crossing_edges_primary + boundary_crossing_edges_secondary +
               boundary_crossing_edges_tertiary) / 2, # divide by 2 for 2-way roads
    lanes = (boundary_crossing_lanes_motorway + boundary_crossing_lanes_trunk +
               boundary_crossing_lanes_primary + boundary_crossing_lanes_secondary +
               boundary_crossing_lanes_tertiary),
    people_per_lanes = ifelse(lanes == 0, 0, Total.Popu / lanes)
  )
zero_roads<-subset(roads, exits == 0) #548
one_roads<-subset(roads, exits <=2 ) #4202
sum(one_roads$Total.Popu)
# ----------------------
# 5. Helper function for scaling with clipping at 99th percentile
# ----------------------
scale01_p99 <- function(x) {
  p99 <- quantile(x, 0.99, na.rm = TRUE)
  x_clipped <- pmin(x, p99)
  scaled <- (x_clipped - min(x_clipped, na.rm = TRUE)) / (p99 - min(x_clipped, na.rm = TRUE))
  return(as.numeric(scaled))
}


# ----------------------
# 6. Test sensitivity of burn permimeter decision
# ----------------------

# Perform the paired t-test
burn_prob_ttest <- t.test(
  roads$bp_mean,
  roads$bp_mean_perim05,
  paired = TRUE
)

# View results
print(burn_prob_ttest)

#The results indicate a statistically significant difference between the two measures (t = -41.995, df = 30,264, p < 2.2e-16). On average, the mean burn probability was approximately 0.000166 lower than the mean perimeter burn probability, with a 95% confidence interval for the difference ranging from -0.000174 to -0.000158.
#While the difference is statistically significant, the magnitude of the difference is small, suggesting that mean and maximum burn probabilities are closely aligned but not identical across communities.

burn_prob_ttest <- t.test(
  roads$bp_mean_perim2,
  roads$bp_mean_perim05,
  paired = TRUE
)

#Although the 2 km buffer had a slightly higher average burn probability than the 0.5 km buffer (mean difference = 9.26e-05, p < 0.001), the difference was minimal, so the 0.5 km buffer was retained for analysis.

burn_prob_ttest <- t.test(
  roads$bp_max_perim2,
  roads$bp_max_perim05,
  paired = TRUE
)

#The 2 km buffer had a higher maximum burn probability than the 0.5 km buffer (mean difference = 0.00047, p < 0.001), but the difference was small, so the 0.5 km buffer was retained for consistency in the analysis.


# ----------------------
# 6. Calculate vulnerability and hazard bins
# ----------------------
roads <- roads %>%
  filter(!is.na(exits), !is.na(bp_mean_perim05), !is.na(bp_max_perim05), !is.na(Total.Popu)) %>%
  mutate(
    # Normalize for composite index
    norm_exits = scale01_p99(max(exits, na.rm = TRUE) - exits),      # vulnerability: fewer exits → higher normalized risk
    norm_hazard = scale01_p99((bp_mean_perim05 + bp_max_perim05) / 2), # wildfire hazard
    norm_population = scale01_p99(Total.Popu),                        # exposure
    
    # Composite wildfire risk index (multiplicative)
    wildfire_risk = norm_exits * norm_hazard * norm_population,
    
    # Binning with fixed cutoffs for exits
    evac_vuln_bin = cut(
      exits,
      breaks = c(-Inf, 6, Inf),
      labels = c("High", "Low"),
      right = TRUE
    ),
    
    hazard_bin = cut((bp_mean_perim05 + bp_max_perim05) / 2,
                     breaks = quantile((bp_mean_perim05 + bp_max_perim05) / 2, probs = c(0, 0.5, 0.9, 1), na.rm = TRUE),
                     labels = c("Low", "Moderate", "High"),
                     include.lowest = TRUE),
    
    pop_bin = cut(Total.Popu,
                  breaks = quantile(Total.Popu, probs = seq(0, 1, 0.25), na.rm = TRUE),
                  labels = c("Low", "Moderate", "High", "Very High"),
                  include.lowest = TRUE)
  )



quantile(roads$exits, probs = c(0, 0.5, 0.75, 1), na.rm = TRUE)
quantile(roads$Total.Popu, probs = c(0, 0.25, 0.75, 1), na.rm = TRUE)
quantile((roads$bp_mean_perim05 + roads$bp_max_perim05) / 2, probs = c(0, 0.5, 0.9, 1))*100


# ----------------------
# 7. Risk calculations
# ----------------------
roads <- roads %>%
  mutate(
    risk = norm_hazard * norm_exits * norm_population,
    log_hazard = log1p(norm_hazard),
    log_exposure = log1p(norm_population),
    risk_log = log_hazard * norm_exits * log_exposure,
    norm_risk_log = scale01_p99(risk_log),
    risk_asin_sqrt = asin(sqrt(risk)),  # arcsine square root transform
    norm_risk_asin_sqrt = scale01_p99(risk_asin_sqrt)  # scaled version for plotting
  )


# ----------------------
# 8. Bivariate color palette and categorization
# ----------------------
bivariate_colors_exits <- c(
  "Low.Low" = "#57A5D9",
  "Moderate.Low" = "#89BBE1",
  "High.Low" = "#BAD0EA",
  "Very High.Low" = "#ECE6F2",
  "Low.Moderate" = "#6175A7",
  "Moderate.Moderate" = "#8C8BAF",
  "High.Moderate" = "#B6A1B7",
  "Very High.Moderate" = "#E1B7BF",
  "Low.High" = "#624E8C",
  "Moderate.High" = "#89628C",
  "High.High" = "#B0758D",
  "Very High.High" = "#D7898D",
  "Low.Very High" = "#631673",
  "Moderate.Very High" = "#7F3C6B",
  "High.Very High" = "#974A62",
  "Very High.Very High" = "#CC5A5A"
)

#evac (blue) then fire (red)
bivariate_color <- c(
  "Low.Low" = "#e8e8e8",
  "High.Low" = "#b0d5df",
  
  "Low.Moderate" = "#e4acac",
  "High.Moderate" = "#ad9ea5",
  
  "Low.High" = "#c85a5a",
  "High.High" = "#985356"
)


roads <- roads %>%
  mutate(
    hazard_bin = factor(hazard_bin, levels = c("Low", "Moderate", "High")),
    evac_vuln_bin = factor(evac_vuln_bin, levels = c("Low", "High")),
    bivariate_cat = factor(paste(evac_vuln_bin, hazard_bin, sep = "."), levels = names(bivariate_colors_exits))
  )


# ----------------------
# 9. make spatial 
# ----------------------
# Update roads_sf so it includes the new bivariate_cat variable
roads_sf <- st_as_sf(roads, coords = c("INTPTLON", "INTPTLAT"), crs = 4326)

# ----------------------
# 10. Maps 
# ----------------------

hazard<-ggplot(roads_sf) +
  geom_sf(aes(color = hazard_bin), alpha = 1, size=0.01) +
  geom_sf(data = states, color = "black", fill = NA, size = 0.3) +
  scale_color_manual(values = c(
    "Low" = "#fee0d2",
    "Moderate" = "#fc9272",
    "High" = "#a50f15"
  ), na.value = "grey70") +
  theme_classic() +
  labs(
    title = "Hazard") +
  guides(color = guide_legend(), size = guide_legend()) +
  coord_sf(crs = 5070)

vulnerability<-ggplot(roads_sf) +
  geom_sf(aes(color = evac_vuln_bin), alpha = 0.6, size=0.01) +
  geom_sf(data = states, color = "black", fill = NA, size = 0.3) +
  scale_color_manual(values = c(
    "Low" = "#deebf7",
    "Moderate" = "#9ecae1",
    "High" = "#08306b"
  ), na.value = "grey70")+
  scale_size_continuous(range = c(0.1, 1), trans = "sqrt") +
  theme_classic() +
  labs(
    title = "Evacuation Vulnerability") +
  guides(color = guide_legend(), size = guide_legend()) +
  coord_sf(crs = 5070)

exposure<-ggplot(roads_sf) +
  geom_sf(aes(color = pop_bin), alpha = 0.6, size=0.01) +
  geom_sf(data = states, color = "black", fill = NA, size = 0.3) +
  scale_color_manual(values = c(
    "Low" = "#edf8e9",
    "Moderate" = "#a1d99b",
    "High" = "#41ab5d",
    "Very High" = "#006d2c"
  ), na.value = "grey70")+
  scale_size_continuous(range = c(0.1, 1), trans = "sqrt") +
  theme_classic() +
  labs(
    title = "Exposure") +
  guides(color = guide_legend(), size = guide_legend()) +
  coord_sf(crs = 5070)


risk <- ggplot(roads_sf) +
  geom_sf(aes(color = norm_risk_asin_sqrt), alpha = 0.6, size = 0.01) +
  geom_sf(data = states, color = "black", fill = NA, size = 0.3) +
  scale_color_gradient(low = "yellow", high = "red", na.value = "grey70") +
  scale_size_continuous(range = c(0.01, 0.1), trans = "sqrt") +
  theme_classic() +
  labs(
    title = "Risk"
  ) +
  guides(color = guide_colorbar(), size = guide_legend()) +
  coord_sf(crs = 5070)


biv_risk<-ggplot(roads_sf) +
  geom_sf(aes(color = bivariate_cat, size = Total.Popu), alpha = 0.8) +
  geom_sf(data = states, color = "black", fill = NA, size = 0.3) +
  scale_color_manual(values = bivariate_color, na.value = "grey70") +
  scale_size_continuous(range = c(0.01, .1), trans = "sqrt") +
  theme_classic() +
  labs(
    title = "Bivariate Map: Burn Hazard and Evacuation Vulnerability") +
  guides(color = "none", size = guide_legend()) +
  coord_sf(crs = 5070)

# ----------------------
# 8. Bivariate color palette and categorization
# ----------------------

# Define 6-category palette (2 evac levels × 3 hazard levels)

# Assign factors and create bivariate category
roads <- roads %>%
  mutate(
    hazard_bin = factor(hazard_bin, levels = c("Low", "Moderate", "High")),
    evac_vuln_bin = factor(evac_vuln_bin, levels = c("Low", "High")),
    bivariate_cat = factor(paste(evac_vuln_bin, hazard_bin, sep = "."),
                           levels = names(bivariate_color))
  )

# ----------------------
# 9. Convert to spatial object
# ----------------------
roads_sf <- st_as_sf(roads, coords = c("INTPTLON", "INTPTLAT"), crs = 4326)

# ----------------------
# 10. Bivariate key with population counts (ordered Low → Moderate → High)
# ----------------------

# Count total population in each bivariate category
bivariate_counts <- roads %>%
  group_by(bivariate_cat) %>%
  summarise(total_pop = sum(Total.Popu, na.rm = TRUE)) %>%
  mutate(label = scales::comma(round(total_pop)))

# Define level orders
evac_levels <- c("Low", "High")
hazard_levels <- c("Low", "Moderate", "High")

# Create bivariate legend data with population labels
bivariate_legend <- expand_grid(
  evac_vuln_bin = evac_levels,
  hazard_bin = hazard_levels
) %>%
  mutate(
    evac_vuln_bin = factor(evac_vuln_bin, levels = evac_levels),
    hazard_bin = factor(hazard_bin, levels = hazard_levels),
    bivariate_cat = paste(evac_vuln_bin, hazard_bin, sep = ".")
  ) %>%
  left_join(bivariate_counts, by = "bivariate_cat") %>%
  mutate(fill = bivariate_color[bivariate_cat])

# Plot the bivariate key
bivariate_key <- ggplot(bivariate_legend, aes(x = hazard_bin, y = evac_vuln_bin)) +
  geom_tile(aes(fill = fill), color = "white") +
  geom_text(aes(label = label,
                color = ifelse(bivariate_cat == "High.High", "white", "black")),
            size = 3) +
  scale_color_identity() +
  scale_fill_identity() +
  scale_x_discrete(position = "top") +
  labs(x = "Burn Hazard", y = "Evacuation Vulnerability") +
  theme_minimal() +
  theme(
    axis.title = element_text(size = 10),
    axis.text = element_text(size = 8),
    panel.grid = element_blank()
  )

# Print the key
print(bivariate_key)


# ----------------------
# 11. State-level summaries and plots
# ----------------------
high_hazard <- roads %>% filter(hazard_bin %in% c("High"))
state_summary <- high_hazard %>%
  group_by(state, evac_vuln_bin) %>%
  summarise(num_communities = n(), total_population = sum(Total.Popu, na.rm = TRUE), .groups = "drop")

top_states <- state_summary %>%
  group_by(state) %>%
  summarise(state_total_pop = sum(total_population, na.rm = TRUE)) %>%
  arrange(desc(state_total_pop)) %>%
  slice_head(n = 15) %>%
  pull(state)

filtered_data <- state_summary %>% filter(state %in% top_states) %>%
  left_join(pop_data %>% select(NAME, state_population), by = c("state" = "NAME")) %>%
  mutate(percent_state_pop = 100 * total_population / state_population)

filtered_data$evac_vuln_bin <- factor(
  filtered_data$evac_vuln_bin,
  levels = c("Low", "Moderate", "High", "Very High")
)

filtered_data <- filtered_data %>%
  group_by(state) %>%
  mutate(state_total_communities = sum(num_communities, na.rm = TRUE)) %>%
  ungroup() %>%
  mutate(state = reorder(state, state_total_communities))


# Create the three bar plots p1, p2, p3 here as you have them
# Define custom color palette
custom_colors <- c(
  "Low" = "#deebf7",
  "Moderate" = "#9ecae1",
  "High" = "#08306b"
)

# Plot 1: Number of communities stacked by vulnerability
p1 <- ggplot(filtered_data, aes(x = state, y = num_communities, fill = evac_vuln_bin)) +
  geom_bar(stat = "identity") +
  scale_fill_manual(values = custom_colors, name = "Vulnerability") +
  labs(
    title = "Number of Communities in High Hazard Areas by Evacuation Vulnerability",
    subtitle = "Top 15 states by population at risk",
    x = "State",
    y = "Number of Communities"
  ) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        legend.position = "bottom") +
  coord_flip()

# Plot 2: Population stacked by vulnerability
p2 <- ggplot(filtered_data, aes(x = state, y = total_population/1000000, fill = evac_vuln_bin)) +
  geom_bar(stat = "identity") +
  scale_fill_manual(values = custom_colors, name = "Vulnerability") +
  labs(
    title = "Population in High Hazard Areas by Evacuation Vulnerability",
    subtitle = "Top 15 states by population at risk",
    x = "State",
    y = "Population (millions)"
  ) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        legend.position = "bottom") +
  coord_flip()

# Plot 3: Percent of state population stacked by vulnerability
p3 <- ggplot(filtered_data, aes(x = state, y = percent_state_pop, fill = evac_vuln_bin)) +
  geom_bar(stat = "identity") +
  scale_fill_manual(values = custom_colors, name = "Vulnerability") +
  labs(
    title = "Percent of State Population in High Hazard Areas by Evacuation Vulnerability",
    subtitle = "Top 15 states by population at risk",
    x = "State",
    y = "Percent of State Population"
  ) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        legend.position = "bottom") +
  coord_flip()

# Print plots
print(p1)
print(p2)
print(p3)


# Add rankings 
roads <- roads %>%
  mutate(
    rank_risk = min_rank(desc(wildfire_risk)),
    rank_hazard = min_rank(desc(norm_hazard)),
    rank_pop = min_rank(desc(norm_population)),
    rank_evac_vuln = min_rank(desc(norm_exits))
  )


write.csv(roads, "roads_for_stats.csv")

# Save maps
ggsave("~/papers/roads/paper-figures/map_hazard.png", hazard, width = 8, height = 6, dpi = 300)
ggsave("~/papers/roads/paper-figures/map_vulnerability.png", vulnerability, width = 8, height = 6, dpi = 300)
ggsave("~/papers/roads/paper-figures/map_exposure.png", exposure, width = 8, height = 6, dpi = 300)
ggsave("~/papers/roads/paper-figures/map_risk.png", risk, width = 8, height = 6, dpi = 300)
ggsave("~/papers/roads/paper-figures/map_biv_risk.png", biv_risk, width = 8, height = 6, dpi = 300)

# Save plots
ggsave("~/papers/roads/paper-figures/plot_num_communities.png", p1, width = 3, height = 4, dpi = 300)
ggsave("~/papers/roads/paper-figures/plot_population.png", p2, width = 3, height = 4, dpi = 300)
ggsave("~/papers/roads/paper-figures/plot_percent_state_pop.png", p3, width = 3, height = 4, dpi = 300)
ggsave("~/papers/roads/paper-figures/key_biv_risk.png", bivariate_key, width = 4, height = 3, dpi = 300)

